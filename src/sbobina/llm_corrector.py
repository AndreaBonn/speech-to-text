from __future__ import annotations

import logging
import re
from importlib import resources
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ValidationError

from sbobina.correction import (
    Corrector,
    CorrectorUnavailableError,
    Edit,
    InvalidResponseError,
)

if TYPE_CHECKING:
    from ollama import ChatResponse

logger = logging.getLogger(__name__)

PROMPT_FILE = "correzione-v1.md"
CONTEXT_WINDOW_TOKENS = 8192
# Ollama 0.18 does not enforce `format` when thinking is off (measured with
# qwen3.5:9b): the JSON then arrives wrapped in a markdown fence.
_MARKDOWN_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class _ProposedEdit(BaseModel):
    originale: str
    corretto: str


class _CorrectionResponse(BaseModel):
    correzioni: list[_ProposedEdit]


def build_system_prompt(subject: str | None) -> str:
    template = (
        resources.files("sbobina.prompts")
        .joinpath(PROMPT_FILE)
        .read_text(encoding="utf-8")
    )
    subject_line = f"\nMateria della lezione: {subject}.\n" if subject else ""
    return template.replace("{materia}", subject_line)


def build_user_message(text: str, context: str) -> str:
    previous = context or "(inizio della lezione)"
    return (
        f"Paragrafo precedente, solo come contesto (non correggerlo):\n{previous}\n\n"
        f"Testo da correggere:\n{text}"
    )


def parse_response(content: str) -> list[Edit]:
    """Validate the model's JSON; raise ``InvalidResponseError`` when it is unusable."""
    fenced = _MARKDOWN_FENCE.match(content)
    payload = fenced.group(1) if fenced else content
    try:
        response = _CorrectionResponse.model_validate_json(payload)
    except ValidationError as err:
        logger.warning("Risposta del modello non valida, paragrafo saltato: %s", err)
        raise InvalidResponseError(str(err)) from err
    return [
        Edit(original=e.originale, corrected=e.corretto) for e in response.correzioni
    ]


def make_ollama_corrector(model: str, host: str, subject: str | None) -> Corrector:
    """Build a ``Corrector`` backed by a local Ollama model."""
    from ollama import Client, ResponseError

    client = Client(host=host)
    system_prompt = build_system_prompt(subject)

    def correct(text: str, context: str) -> list[Edit]:
        try:
            response = _chat(text, context)
        # ResponseError: model missing or server error; TransportError: the
        # server died mid-answer (e.g. out of GPU memory).
        except (ConnectionError, ResponseError, httpx.TransportError) as err:
            raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
        # The server answered 200 with a body that is not JSON (truncated reply):
        # it is reachable, so skip this chunk instead of stopping the run.
        except ValueError as err:
            raise InvalidResponseError(f"{type(err).__name__}: {err}") from err
        return parse_response(response.message.content or "")

    def _chat(text: str, context: str) -> ChatResponse:
        return client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_user_message(text, context)},
            ],
            format=_CorrectionResponse.model_json_schema(),
            think=False,
            options={"temperature": 0, "num_ctx": CONTEXT_WINDOW_TOKENS},
        )

    return correct
