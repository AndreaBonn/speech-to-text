"""Settings page API: engine, chain, transcription engine and API keys.

Every mutation needs an Origin header equal to the app's own (S2): the global
OriginMiddleware lets a mutation without Origin through, and these routes
decide where lecture text and audio are sent. Reads only refuse a foreign
Origin, since browsers send none on same-origin GETs.
"""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, JsonValue, StringConstraints

from sbobina import key_check, settings_service
from sbobina.config_dir import ConfigDirUnsafeError
from sbobina.credential_store import MAX_KEY_LENGTH, InvalidKeyError
from sbobina.runtime_config import runtime_keys
from sbobina.settings import LlmChainEntry, Settings, TranscriptionEngine
from sbobina.web.errors import ConflictError, ForbiddenError, NotFoundError
from sbobina.web.errors import ValidationError as AppValidationError
from sbobina.web.middleware import web_origin

_CLOUD_ACK_MESSAGE = "Conferma che i dati verranno inviati ai servizi scelti"


class LlmSettingsBody(BaseModel):
    llm_engine: Literal["local", "api"]
    llm_chain: list[LlmChainEntry] = Field(default_factory=list)
    llm_ollama_fallback: bool = True
    cloud_ack: bool = False


class TranscriptionSettingsBody(BaseModel):
    transcription_engine: TranscriptionEngine
    cloud_ack_audio: bool = False


class KeyBody(BaseModel):
    key: str = Field(max_length=MAX_KEY_LENGTH)


class SemanticIndexSettingsBody(BaseModel):
    embedding_model: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]
    semantic_search: bool


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    # Browsers omit Origin on same-origin GETs: a read needs only that a
    # present Origin is ours (the view is masked); a write needs it present.
    is_read = request.method == "GET"
    if (origin is None and not is_read) or (
        origin is not None and origin != web_origin(settings=settings)
    ):
        raise ForbiddenError(
            message="Origine della richiesta non consentita", code="FORBIDDEN"
        )
    return settings


SettingsDep = Annotated[Settings, Depends(_settings)]


def _known(provider: str) -> str:
    if not settings_service.is_known_provider(provider=provider):
        raise NotFoundError(entity="Provider", id=provider)
    return provider


def _save[T](action: Callable[[], T]) -> T:
    """Map the service's rule violations to HTTP errors."""
    try:
        return action()
    except ConfigDirUnsafeError as error:
        raise ConflictError(
            message="Cartella di configurazione non sicura: impostazioni in sola lettura",
            code="CONFIG_DIR_UNSAFE",
        ) from error
    except settings_service.CloudAckRequiredError as error:
        raise ConflictError(
            message=_CLOUD_ACK_MESSAGE, code="CLOUD_ACK_REQUIRED"
        ) from error
    except settings_service.LockedByEnvError as error:
        raise ConflictError(
            message=f"Impostato da variabile d'ambiente: {error.field}",
            code="LOCKED_BY_ENV",
        ) from error


router = APIRouter(prefix="/api/v1/settings")


@router.get("")
def read_settings(settings: SettingsDep) -> dict[str, JsonValue]:
    return {"data": settings_service.settings_view(settings=settings)}


@router.put("/llm")
def put_llm(body: LlmSettingsBody, settings: SettingsDep) -> dict[str, JsonValue]:
    update = settings_service.LlmUpdate(**body.model_dump())
    _save(lambda: settings_service.update_llm(settings=settings, update=update))
    return {"data": settings_service.settings_view(settings=settings)}


@router.put("/transcription")
def put_transcription(
    body: TranscriptionSettingsBody, settings: SettingsDep
) -> dict[str, JsonValue]:
    update = settings_service.TranscriptionUpdate(**body.model_dump())
    _save(
        lambda: settings_service.update_transcription(settings=settings, update=update)
    )
    return {"data": settings_service.settings_view(settings=settings)}


@router.put("/keys/{provider}")
def put_key(
    provider: str, body: KeyBody, settings: SettingsDep
) -> dict[str, JsonValue]:
    known = _known(provider=provider)
    try:
        view = _save(
            lambda: settings_service.set_key(
                settings=settings, provider=known, key=body.key
            )
        )
    except InvalidKeyError as error:
        raise AppValidationError(message=str(error)) from error
    return {"data": view}


@router.put("/semantic-index")
def put_semantic_index(
    body: SemanticIndexSettingsBody, settings: SettingsDep
) -> dict[str, JsonValue]:
    update = settings_service.SemanticIndexUpdate(**body.model_dump())
    _save(
        lambda: settings_service.update_semantic_index(settings=settings, update=update)
    )
    return {"data": settings_service.settings_view(settings=settings)}


@router.delete("/keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(provider: str, settings: SettingsDep) -> Response:
    known = _known(provider=provider)
    _save(lambda: settings_service.delete_key(settings=settings, provider=known))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/keys/{provider}/test")
def test_key(provider: str, settings: SettingsDep) -> dict[str, JsonValue]:
    known = _known(provider=provider)
    result = key_check.check_key(
        provider=known,
        api_key=runtime_keys(settings=settings).get(known),
        timeout_s=settings.cloud_timeout_s,
    )
    return {"data": {"provider": known, "result": result}}
