import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock, patch

import ollama
import pytest
from fastapi.testclient import TestClient
from huggingface_hub.errors import LocalEntryNotFoundError

from sbobina.settings import Settings
from sbobina.web import model_service
from sbobina.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"
OLLAMA_MODEL = {"model": "qwen3.5:9b", "size": 1024, "parameter_size": "9B"}
OLLAMA_RESPONSE = {
    "models": [
        {"model": "qwen3.5:9b", "size": 1024, "details": {"parameter_size": "9B"}}
    ]
}
EXPECTED_TINY = {
    "name": "tiny",
    "repo_id": "Systran/faster-whisper-tiny",
    "aliases": [],
    "downloaded": False,
    "size_bytes": None,
    "recommended_gpu": False,
    "recommended_cpu": False,
}


@pytest.fixture
def models_probe(tmp_path: Path) -> Iterator[tuple[TestClient, Mock]]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with (
        patch.object(
            model_service,
            "download_model",
            side_effect=LocalEntryNotFoundError("missing"),
        ),
        patch.object(ollama, "Client") as factory,
        patch.object(shutil, "which", return_value=None),
        patch.object(sys, "platform", "linux"),
    ):
        transport = TestClient(app=app, base_url=BASE_URL)
        client = factory.return_value.__enter__.return_value
        client.list.return_value = ollama.ListResponse.model_validate(OLLAMA_RESPONSE)
        yield transport, client
        transport.close()


@pytest.mark.parametrize(
    ("is_ready", "expected_status", "expected_message"),
    [
        (True, "ready", "Ollama è pronto."),
        (
            False,
            "not_installed",
            "Ollama non è disponibile. Installa Ollama da https://ollama.com.",
        ),
    ],
)
def test_models_endpoint_returns_catalog_and_ollama_state(
    models_probe: tuple[TestClient, Mock],
    is_ready: bool,
    expected_status: str,
    expected_message: str,
) -> None:
    transport, client = models_probe
    populated = transport.get("/api/v1/models")
    assert populated.status_code == 200
    assert populated.json()["data"]["ollama"]["models"] == [OLLAMA_MODEL]
    client.list.return_value = ollama.ListResponse(models=[])
    client.list.side_effect = None if is_ready else ConnectionError("refused")

    response = transport.get("/api/v1/models")

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"whisper", "ollama"}
    assert (
        next(model for model in data["whisper"] if model["name"] == "tiny")
        == EXPECTED_TINY
    )
    assert data["ollama"]["status"] == expected_status
    assert data["ollama"]["message"] == expected_message
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
