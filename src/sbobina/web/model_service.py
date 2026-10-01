import logging
import shutil
import sys
from pathlib import Path

import httpx
import ollama
from faster_whisper.utils import _MODELS, available_models, download_model
from huggingface_hub.errors import LocalEntryNotFoundError
from pydantic import JsonValue

from sbobina.settings import Settings

logger = logging.getLogger(__name__)
OLLAMA_STATUS_TIMEOUT = 3.0


def _cached_model_size(name: str) -> int | None:
    try:
        directory = Path(download_model(size_or_id=name, local_files_only=True))
    except LocalEntryNotFoundError:
        logger.debug("Whisper model %s is not cached", name)
        return None
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def list_whisper_models(settings: Settings) -> list[dict[str, JsonValue]]:
    """List repository-deduplicated Whisper models with local cache sizes in bytes."""
    repositories: dict[str, list[str]] = {}
    for name in available_models():
        repositories.setdefault(_MODELS[name], []).append(name)
    models: list[dict[str, JsonValue]] = []
    for repo_id, names in repositories.items():
        name = next(candidate for candidate in _MODELS if candidate in names)
        size = _cached_model_size(name=name)
        models.append(
            {
                "name": name,
                "repo_id": repo_id,
                "aliases": [alias for alias in names if alias != name],
                "downloaded": size is not None,
                "size_bytes": size,
                "recommended_gpu": settings.whisper_model_gpu in names,
                "recommended_cpu": settings.whisper_model_cpu in names,
            }
        )
    return models


def _unavailable_ollama_status() -> dict[str, JsonValue]:
    is_installed = shutil.which("ollama") is not None
    if not is_installed:
        action = (
            "Installa Ollama da https://ollama.com."
            if sys.platform == "linux"
            else "Scarica l'app Ollama da https://ollama.com."
        )
    else:
        action = (
            "Avvia ollama serve." if sys.platform == "linux" else "Avvia l'app Ollama."
        )
    return {
        "status": "not_running" if is_installed else "not_installed",
        "message": f"Ollama non è disponibile. {action}",
        "models": [],
    }


def ollama_status(host: str) -> dict[str, JsonValue]:
    """Probe Ollama and return its state, user action and installed models."""
    try:
        with ollama.Client(host=host, timeout=OLLAMA_STATUS_TIMEOUT) as client:
            models = client.list().models
    except (ConnectionError, ollama.ResponseError, httpx.HTTPError) as error:
        logger.warning("Ollama status check failed: %s", error)
        return _unavailable_ollama_status()
    return {
        "status": "ready",
        "message": "Ollama è pronto.",
        "models": [{"model": model.model, "size": model.size} for model in models],
    }
