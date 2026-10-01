import shutil
from pathlib import Path
from unittest.mock import patch

import ollama
import pytest
from fastapi.testclient import TestClient
from huggingface_hub.errors import LocalEntryNotFoundError

from sbobina.settings import Settings
from sbobina.web import model_service
from sbobina.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"
EXPECTED_TINY = {
    "name": "tiny",
    "repo_id": "Systran/faster-whisper-tiny",
    "aliases": [],
    "downloaded": False,
    "size_bytes": None,
    "recommended_gpu": False,
    "recommended_cpu": False,
}


@pytest.mark.parametrize("is_ready", [False, True])
def test_models_endpoint_returns_catalog_and_ollama_state(
    tmp_path: Path, is_ready: bool
) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with (
        patch.object(model_service, "available_models", return_value=["tiny"]),
        patch.object(
            model_service,
            "download_model",
            side_effect=LocalEntryNotFoundError("missing"),
        ),
        patch.object(ollama, "Client") as factory,
        patch.object(shutil, "which", return_value=None),
    ):
        client = factory.return_value.__enter__.return_value
        client.list.return_value = ollama.ListResponse(models=[])
        client.list.side_effect = None if is_ready else ConnectionError("refused")
        response = TestClient(app, base_url=BASE_URL).get("/api/v1/models")
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"whisper", "ollama"}
    assert data["whisper"] == [EXPECTED_TINY]
    assert data["ollama"]["status"] == ("ready" if is_ready else "not_installed")
    assert data["ollama"]["message"]
    assert data["ollama"]["models"] == []


@pytest.mark.parametrize("path", ["/api/v1/system", "/api/v1/models"])
def test_endpoints_share_ollama_payload(tmp_path: Path, path: str) -> None:
    app = create_app(settings=Settings(device="cpu"), data_dir=tmp_path)
    with (
        patch.object(model_service, "available_models", return_value=[]),
        patch.object(ollama, "Client") as factory,
    ):
        factory.return_value.__enter__.return_value.list.return_value = (
            ollama.ListResponse.model_validate(
                {"models": [{"model": "qwen3.5:9b", "size": 1024}]}
            )
        )
        response = TestClient(app, base_url=BASE_URL).get(path)
    assert response.status_code == 200
    assert response.json()["data"]["ollama"] == {
        "status": "ready",
        "message": "Ollama è pronto.",
        "models": [{"model": "qwen3.5:9b", "size": 1024, "parameter_size": None}],
    }
