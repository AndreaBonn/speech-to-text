import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
import anyio.to_thread
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import JsonValue

from sbobina.runtime_config import runtime_settings
from sbobina.settings import Settings
from sbobina.web.downloads import DownloadManager, DownloadRequest, DownloadState
from sbobina.web.model_service import list_whisper_models, ollama_roles, ollama_status

DOWNLOADS_POLL_INTERVAL_S = 0.5
DOWNLOADS_PING_INTERVAL_S = 15.0


def _encode_event(event: str, data: dict[str, JsonValue]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _signature(state: DownloadState) -> tuple[Any, ...]:
    return (state.status, state.completed, state.total)


async def _download_events(
    request: Request, manager: DownloadManager
) -> AsyncIterator[str]:
    previous: dict[tuple[str, str], tuple[Any, ...]] = {}
    ended: set[tuple[str, str]] = set()
    last_sent = anyio.current_time()
    while not await request.is_disconnected():
        states = await anyio.to_thread.run_sync(manager.list)
        sent = False
        for state in states:
            key = (state.source, state.name)
            signature = _signature(state=state)
            if previous.get(key) != signature:
                yield _encode_event(event="progress", data=state.to_json())
                previous[key] = signature
                sent = True
            if state.status in ("done", "failed") and key not in ended:
                yield _encode_event(event="end", data=state.to_json())
                ended.add(key)
                sent = True
        if sent:
            last_sent = anyio.current_time()
        elif anyio.current_time() - last_sent >= DOWNLOADS_PING_INTERVAL_S:
            yield ": ping\n\n"
            last_sent = anyio.current_time()
        await anyio.sleep(DOWNLOADS_POLL_INTERVAL_S)


def _roles_by_model(
    ollama: dict[str, JsonValue], settings: Settings
) -> dict[str, JsonValue]:
    """M3: model name -> what the app uses it for. Kept beside the Ollama
    block so /system and /models still share that block unchanged."""
    effective = runtime_settings(settings=settings)
    models = ollama.get("models")
    if not isinstance(models, list):
        return {}
    return {
        str(model["model"]): list(
            ollama_roles(name=str(model["model"]), settings=effective)
        )
        for model in models
        if isinstance(model, dict) and "model" in model
    }


def create_models_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/models")
    def models_info() -> dict[str, dict[str, JsonValue]]:
        whisper: list[JsonValue] = [
            model for model in list_whisper_models(settings=settings)
        ]
        ollama = ollama_status(host=settings.ollama_host)
        return {
            "data": {
                "whisper": whisper,
                "ollama": ollama,
                "ollama_roles": _roles_by_model(ollama=ollama, settings=settings),
            }
        }

    @router.post("/models/downloads", status_code=202)
    def start_download(
        request: Request, body: DownloadRequest
    ) -> dict[str, dict[str, JsonValue]]:
        manager: DownloadManager = request.app.state.download_manager
        state = manager.start(source=body.source, name=body.name)
        return {"data": state.to_json()}

    @router.get("/models/downloads")
    def list_downloads(request: Request) -> dict[str, list[JsonValue]]:
        manager: DownloadManager = request.app.state.download_manager
        return {"data": [state.to_json() for state in manager.list()]}

    @router.get("/models/downloads/events", response_class=StreamingResponse)
    async def download_events(request: Request) -> StreamingResponse:
        manager: DownloadManager = request.app.state.download_manager
        return StreamingResponse(
            content=_download_events(request=request, manager=manager),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return router
