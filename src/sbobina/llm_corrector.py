from __future__ import annotations

import logging
from importlib import resources

import httpx
from pydantic import BaseModel, ValidationError

from sbobina.correction import (
    Corrector,
    CorrectorUnavailableError,
    Edit,
    InvalidResponseError,
)
from sbobina.notices import USER_NOTICE
from sbobina.ollama_chat import ChatRequest, chat_json, strip_markdown_fence

logger = logging.getLogger(__name__)

PROMPT_FILE = "correzione-v1.md"
HTTP_NOT_FOUND = 404


class ModelDownloadError(RuntimeError):
    """Ollama is reachable but could not download the requested model."""


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
    payload = strip_markdown_fence(content=content)
    try:
        response = _CorrectionResponse.model_validate_json(payload)
    except ValidationError as err:
        logger.warning("Risposta del modello non valida, paragrafo saltato: %s", err)
        raise InvalidResponseError(str(err)) from err
    return [
        Edit(original=e.originale, corrected=e.corretto) for e in response.correzioni
    ]


def ensure_model(model: str, host: str) -> bool:
    """Download ``model`` into Ollama when it is missing; return True if pulled.

    Raises
    ------
    CorrectorUnavailableError
        Ollama cannot be reached.
    ModelDownloadError
        Ollama refused the download, typically a misspelled model name.
    """
    from ollama import Client, ResponseError

    client = Client(host=host)
    try:
        client.show(model)
        return False
    except ResponseError as err:
        if err.status_code != HTTP_NOT_FOUND:
            raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
    except (ConnectionError, httpx.TransportError) as err:
        raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
    logger.info(
        "Scarico il modello Ollama %s: la prima volta può richiedere diversi minuti",
        model,
        extra={USER_NOTICE: True},
    )
    try:
        client.pull(model=model)
    except ResponseError as err:
        raise ModelDownloadError(f"Download di {model} non riuscito: {err}") from err
    except (ConnectionError, httpx.TransportError) as err:
        raise CorrectorUnavailableError(f"{type(err).__name__}: {err}") from err
    return True


def make_ollama_corrector(model: str, host: str, subject: str | None) -> Corrector:
    """Build a ``Corrector`` backed by a local Ollama model."""
    from ollama import Client

    client = Client(host=host)
    system_prompt = build_system_prompt(subject)

    def correct(text: str, context: str) -> list[Edit]:
        request = ChatRequest(
            model=model,
            system_prompt=system_prompt,
            user_message=build_user_message(text=text, context=context),
            schema=_CorrectionResponse.model_json_schema(),
        )
        return parse_response(content=chat_json(client=client, request=request))

    return correct
