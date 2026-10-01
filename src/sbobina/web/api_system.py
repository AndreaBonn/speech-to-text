from fastapi import APIRouter
from pydantic import JsonValue

from sbobina import platform_info
from sbobina.settings import Settings


def create_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/system")
    def system_info() -> dict[str, dict[str, JsonValue]]:
        info = platform_info.detect_platform()
        requested = platform_info.RuntimeRequest(
            device=settings.device,
            compute_type=settings.compute_type,
            whisper_model=settings.whisper_model,
            whisper_model_gpu=settings.whisper_model_gpu,
            whisper_model_cpu=settings.whisper_model_cpu,
            cpu_threads=settings.cpu_threads,
        )
        runtime = platform_info.resolve_runtime(info=info, requested=requested)
        return {
            "data": {
                "os": info.system,
                "device": runtime.device,
                "compute_type": runtime.compute_type,
                "whisper_model": runtime.whisper_model,
                "reason": runtime.reason,
                "cuda_libs_available": info.cuda_libs_available,
            }
        }

    return router
