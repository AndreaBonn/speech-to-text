"""Repair a model's best-effort JSON reply: fences, LaTeX, brackets, quotes.

Shared by every chat client (Ollama today, cloud adapters next): the
failure modes come from how a model writes free text that is supposed to
be JSON, not from any single provider's API.
"""

import json
import logging
import re

logger = logging.getLogger("sbobina")

# A model may wrap JSON in a markdown fence when thinking/formatting is off.
_MARKDOWN_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)

_CLOSERS = {"{": "}", "[": "]"}
# What may follow a backslash that starts a real JSON escape. b/f/n/r/t
# followed by a letter are LaTeX commands instead (\frac, \to, \nabla, \beta).
_JSON_ESCAPE = re.compile(r'["\\/]|u[0-9a-fA-F]{4}|[bfnrt](?![A-Za-z])')

# What follows a quote that really closes a JSON string: a key's ":", the end
# of an object or array, the end of the reply, or a comma before the next
# string, object or array (the schemas hold no bare numbers after a string).
_STRING_END = re.compile(r'\s*(?:[:}\]]|$|,\s*["{\[])')


def strip_markdown_fence(content: str) -> str:
    fenced = _MARKDOWN_FENCE.match(content)
    return fenced.group(1) if fenced else content


def escape_latex_backslashes(content: str) -> str:
    r"""Double the backslashes of LaTeX commands written inside JSON strings.

    Measured on qwen3.5:9b with formula passages (T067): replies carry "\(",
    "\eta", "\frac" with a single backslash. "\(" breaks parsing, while
    "\frac" and "\to" parse silently as form feed and tab. A newline escape
    written right before a letter ("\nOra") is read as LaTeX too: the fields
    are sentences, where a newline has no use.
    """
    parts: list[str] = []
    in_string = False
    index = 0
    while index < len(content):
        char = content[index]
        if in_string and char == "\\":
            if _JSON_ESCAPE.match(content, pos=index + 1):
                parts.append(content[index : index + 2])
                index += 2
            else:
                parts.append("\\\\")
                index += 1
            continue
        in_string = in_string != (char == '"')
        parts.append(char)
        index += 1
    return "".join(parts)


def escape_inner_quotes(content: str) -> str:
    """Escape the quotes inside a JSON string that do not close it.

    Measured on a real slide (2026-10-06): qwen copied 'Il "miglior" stato'
    into a citation without escaping, the same at both attempts. A quote
    followed by ":" still reads as a closer, so that case stays broken.
    Copied quotes come in pairs: a string left with an odd number of them
    means a '", "' inside one list item was read as an item boundary, so
    the content comes back untouched.
    """
    parts: list[str] = []
    in_string = False
    escaped = index = 0
    while index < len(content):
        char = content[index]
        step = 2 if in_string and char == "\\" else 1
        if char == '"' and in_string and not _STRING_END.match(content, index + 1):
            parts.append('\\"')
            escaped += 1
        else:
            if char == '"' and in_string and escaped % 2:
                return content
            escaped = 0 if char == '"' else escaped
            in_string = in_string != (char == '"')
            parts.append(content[index : index + step])
        index += step
    return "".join(parts)


def _parses(content: str) -> bool:
    try:
        json.loads(content)
    except json.JSONDecodeError:
        return False
    return True


def _open_brackets(content: str) -> list[str] | None:
    """Unclosed brackets in order, or None if a string is cut or they mismatch."""
    stack: list[str] = []
    in_string = escaped = False
    for char in content:
        if escaped:
            escaped = False
        elif in_string:
            escaped = char == "\\"
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char in _CLOSERS:
            stack.append(char)
        elif char in "}]" and (not stack or _CLOSERS[stack.pop()] != char):
            return None
    return None if in_string else stack


def close_open_brackets(content: str) -> str:
    """Append the closers a reply forgot, never touching what it wrote.

    Measured on qwen3.5:9b (T036): with think=False Ollama does not enforce
    the schema, and a complete summary ended "]}]}]" without its root "}".
    A reply cut inside a string or with mismatched brackets is left as is.
    """
    stack = _open_brackets(content=content)
    if not stack:
        return content
    return content + "".join(_CLOSERS[char] for char in reversed(stack))


def _with_inner_quotes(raw: str, closed: str) -> str:
    """The reply with its inner quotes escaped, only if that makes it parse.

    The quotes are fixed on the raw reply: the LaTeX escaping reads string
    boundaries from the quotes, so it must run after them.
    """
    repaired = close_open_brackets(
        content=escape_latex_backslashes(content=escape_inner_quotes(content=raw))
    )
    if not _parses(content=repaired):
        return closed
    logger.warning("Risposta del modello con virgolette non escapate: corrette")
    return repaired


def repair_json_reply(raw: str, truncated: bool) -> str:
    """Return the best-effort repaired JSON text of a model's reply.

    Strips a markdown fence, doubles single-backslash LaTeX commands, then
    (unless the reply was cut by the output token limit) closes brackets
    the model forgot and, if that still does not parse, escapes unescaped
    inner quotes. The caller validates the task-specific schema.

    Parameters
    ----------
    raw : str
        The raw text content of the model's reply.
    truncated : bool
        Whether the reply was cut by the output token limit. A truncated
        reply is returned without closing its brackets, so the caller's
        retry logic sees that it is incomplete rather than a false "valid".

    Returns
    -------
    str
        The repaired text, or the escaped content unparsed if no repair
        makes it valid JSON.
    """
    unfenced = strip_markdown_fence(content=raw)
    content = escape_latex_backslashes(content=unfenced)
    if truncated:
        return content
    closed = close_open_brackets(content=content)
    if closed != content:
        logger.warning("Risposta del modello con parentesi non chiuse: chiuse in coda")
    return closed if _parses(content=closed) else _with_inner_quotes(unfenced, closed)
