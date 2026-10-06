import logging
from dataclasses import dataclass
from typing import Any

import httpx
from ollama import ChatResponse, Client, ResponseError

from sbobina.correction import CorrectorUnavailableError, InvalidResponseError
from sbobina.llm_repair import (
    close_open_brackets,
    escape_inner_quotes,
    escape_latex_backslashes,
    repair_json_reply,
    strip_markdown_fence,
)

__all__ = [
    "CONTEXT_WINDOW_TOKENS",
    "ChatRequest",
    "chat_json",
    "close_open_brackets",
    "escape_inner_quotes",
    "escape_latex_backslashes",
    "strip_markdown_fence",
]

logger = logging.getLogger("sbobina")

CONTEXT_WINDOW_TOKENS = 8192


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system_prompt: str
    user_message: str
    schema: dict[str, Any]
    num_predict: int | None = None


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
    return repair_json_reply(
        raw=response.message.content or "",
        truncated=response.done_reason == "length",
    )
