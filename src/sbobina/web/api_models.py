from fastapi import APIRouter
from pydantic import JsonValue

from sbobina.settings import Settings
from sbobina.web.model_service import list_whisper_models, ollama_status


def create_models_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/models")
    def models_info() -> dict[str, dict[str, JsonValue]]:
        whisper: list[JsonValue] = [
            model for model in list_whisper_models(settings=settings)
        ]
        return {
            "data": {
                "whisper": whisper,
                "ollama": ollama_status(host=settings.ollama_host),
            }
        }

    return router
