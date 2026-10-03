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
    content = strip_markdown_fence(content=response.message.content or "")
    if response.done_reason == "length":
        return content
    closed = close_open_brackets(content=content)
    if closed != content:
        logger.warning("Risposta di Ollama con parentesi non chiuse: chiuse in coda")
    return closed
