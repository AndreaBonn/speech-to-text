from fastapi import APIRouter
from pydantic import JsonValue

from sbobina import platform_info
from sbobina.settings import Settings
from sbobina.web.model_service import ollama_status


def create_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/system")
    def system_info() -> dict[str, dict[str, JsonValue]]:
        info, runtime = platform_info.resolve_for_settings(config=settings)
        return {
            "data": {
                "os": info.system,
                "device": runtime.device,
                "compute_type": runtime.compute_type,
                "whisper_model": runtime.whisper_model,
                "reason": runtime.reason,
                "cuda_libs_available": info.cuda_libs_available,
                "ollama": ollama_status(host=settings.ollama_host),
            }
        }

    return router
