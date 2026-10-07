from dataclasses import dataclass, replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, JsonValue

from sbobina import ollama_embed
from sbobina.runtime_config import runtime_settings
from sbobina.settings import Settings
from sbobina.web.api_settings import SettingsDep
from sbobina.web.course_actions import submit_embed
from sbobina.web.dense_factory import vector_store_for_process
from sbobina.web.errors import ConflictError
from sbobina.web.job_store import JobStore
from sbobina.web.semantic_index_queue import submit_backfill
from sbobina.web.semantic_index_status import (
    embedding_models_view,
    semantic_index_status,
)
from sbobina.web.supervisor import Supervisor
from sbobina.web.vector_store import VectorStore

router = APIRouter(prefix="/api/v1")


class BackfillBody(BaseModel):
    confirm_model_change: bool


@dataclass(frozen=True)
class SemanticServices:
    settings: Settings
    store: JobStore
    supervisor: Supervisor
    vectors: VectorStore


def _services(request: Request, settings: SettingsDep) -> SemanticServices:
    store = request.app.state.job_store
    return SemanticServices(
        settings=runtime_settings(settings=settings),
        store=store,
        supervisor=request.app.state.supervisor,
        vectors=vector_store_for_process(data_dir=store.jobs_dir.parent),
    )


Services = Annotated[SemanticServices, Depends(_services)]


@router.get("/semantic-index/status")
def read_status(services: Services) -> dict[str, JsonValue]:
    return {
        "data": semantic_index_status(
            settings=services.settings, store=services.store, vectors=services.vectors
        )
    }


@router.get("/settings/embedding-models")
def read_embedding_models(settings: SettingsDep) -> dict[str, JsonValue]:
    return {"data": embedding_models_view(settings=runtime_settings(settings=settings))}


@router.post("/courses/{key}/semantic-index", status_code=202)
def post_course_index(key: str, services: Services) -> dict[str, JsonValue]:
    run = submit_embed(supervisor=services.supervisor, course_key=key)
    return {"data": jsonable_encoder(run)}


def _installed_status(config: Settings) -> ollama_embed.ModelStatus:
    try:
        return ollama_embed.model_status(
            host=config.ollama_host,
            model=config.embedding_model,
            timeout_s=config.embedding_timeout_s,
        )
    except ollama_embed.EmbeddingUnavailableError as error:
        raise ConflictError(
            message="Modello di embedding non disponibile", code=error.reason
        ) from error


@router.post("/semantic-index/backfill", status_code=202)
def post_backfill(body: BackfillBody, services: Services) -> dict[str, JsonValue]:
    config = services.settings
    status = _installed_status(config=config)
    result = submit_backfill(
        supervisor=services.supervisor,
        vectors=services.vectors,
        status=replace(status, model=config.embedding_model),
        confirm_model_change=body.confirm_model_change,
    )
    return {
        "data": {
            "model_change_pending": result.model_change_pending,
            "queued": len(result.items),
        }
    }
