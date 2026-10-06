import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from ollama import ChatResponse, Client, ResponseError

from sbobina.correction import CorrectorUnavailableError, InvalidResponseError

logger = logging.getLogger("sbobina")

CONTEXT_WINDOW_TOKENS = 8192
# Ollama 0.18 may wrap JSON in a fence when thinking is disabled.
_MARKDOWN_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system_prompt: str
    user_message: str
    schema: dict[str, Any]
    num_predict: int | None = None


_CLOSERS = {"{": "}", "[": "]"}
# What may follow a backslash that starts a real JSON escape. b/f/n/r/t
# followed by a letter are LaTeX commands instead (\frac, \to, \nabla, \beta).
_JSON_ESCAPE = re.compile(r'["\\/]|u[0-9a-fA-F]{4}|[bfnrt](?![A-Za-z])')


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


# What follows a quote that really closes a JSON string: a key's ":", the end
# of an object or array, the end of the reply, or a comma before the next
# string, object or array (the schemas hold no bare numbers after a string).
_STRING_END = re.compile(r'\s*(?:[:}\]]|$|,\s*["{\[])')


def escape_inner_quotes(content: str) -> str:
    """Escape the quotes inside a JSON string that do not close it.

    Measured on a real slide (2026-10-06): qwen copied 'Il "miglior" stato'
    into a citation without escaping, the same at both attempts, and the
    summary lost the section. A quote followed by ":" still reads as a
    closer, so that case stays broken. Copied quotes come in pairs: a string
    left with an odd number of them means a '", "' inside one list item was
    read as an item boundary, so the content comes back untouched.
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


def strip_markdown_fence(content: str) -> str:
    fenced = _MARKDOWN_FENCE.match(content)
    return fenced.group(1) if fenced else content


def _log_usage(response: ChatResponse) -> None:
    # Token counts size the material budget (generation_runner); a reply cut at
    # num_predict is invalid JSON, so the cause must be visible in the log.
    logger.info(
        "Ollama: prompt_tokens=%s output_tokens=%s done_reason=%s",
        response.prompt_eval_count,
        response.eval_count,
        response.done_reason,
    )
    if response.done_reason == "length":
        logger.warning("Risposta di Ollama troncata al limite di token in uscita")


def chat_json(client: Client, request: ChatRequest) -> str:
    """Return unfenced content; the caller validates its task-specific schema."""
    options = {"temperature": 0, "num_ctx": CONTEXT_WINDOW_TOKENS}
    if request.num_predict is not None:
        options["num_predict"] = request.num_predict
    try:
        response = client.chat(
            model=request.model,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            format=request.schema,
            think=False,
            options=options,
        )
    except (ConnectionError, ResponseError, httpx.TransportError) as err:
        raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
    except ValueError as err:
        raise InvalidResponseError(f"{type(err).__name__}: {err}") from err
    _log_usage(response=response)
    raw = strip_markdown_fence(content=response.message.content or "")
    content = escape_latex_backslashes(content=raw)
    if response.done_reason == "length":
        return content
    closed = close_open_brackets(content=content)
    if closed != content:
        logger.warning("Risposta di Ollama con parentesi non chiuse: chiuse in coda")
    return closed if _parses(content=closed) else _with_inner_quotes(raw, closed)


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
    logger.warning("Risposta di Ollama con virgolette non escapate: corrette")
    return repaired
