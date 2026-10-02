import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import ollama
import pytest
from huggingface_hub.errors import IncompleteSnapshotError, LocalEntryNotFoundError

from sbobina.settings import Settings
from sbobina.web import model_service

HOST = "http://127.0.0.1:11434"


def test_whisper_models_deduplicate_aliases_and_measure_cached_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "model.bin").write_bytes(b"weights")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "config.json").write_bytes(b"{}")
    with (
        patch.object(
            model_service, "available_models", return_value=["large", "large-v3"]
        ),
        patch.object(
            model_service, "download_model", return_value=str(tmp_path)
        ) as hub,
    ):
        models = model_service.list_whisper_models(
            settings=Settings(whisper_model_gpu="large")
        )
    assert models == [
        {
            "name": "large-v3",
            "repo_id": "Systran/faster-whisper-large-v3",
            "aliases": ["large"],
            "downloaded": True,
            "size_bytes": 9,
            "recommended_gpu": True,
            "recommended_cpu": False,
        }
    ]
    hub.assert_called_once_with(size_or_id="large-v3", local_files_only=True)


@pytest.mark.parametrize(
    "error",
    [
        LocalEntryNotFoundError("missing"),
        IncompleteSnapshotError(message="missing", snapshot_path="/cache"),
    ],
)
def test_whisper_models_missing_cache_and_cpu_alias(
    error: Exception,
) -> None:
    with (
        patch.object(
            model_service, "available_models", return_value=["turbo", "large-v3-turbo"]
        ),
        patch.object(model_service, "download_model", side_effect=error),
    ):
        models = model_service.list_whisper_models(
            settings=Settings(whisper_model_cpu="turbo")
        )
    assert models == [
        {
            "name": "large-v3-turbo",
            "repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            "aliases": ["turbo"],
            "downloaded": False,
            "size_bytes": None,
            "recommended_gpu": False,
            "recommended_cpu": True,
        }
    ]


def test_whisper_models_propagate_unexpected_cache_error() -> None:
    with (
        patch.object(model_service, "available_models", return_value=["tiny"]),
        patch.object(
            model_service, "download_model", side_effect=PermissionError("denied")
        ),
        pytest.raises(PermissionError, match="denied"),
    ):
        model_service.list_whisper_models(settings=Settings())


def test_whisper_models_empty_catalog() -> None:
    with patch.object(model_service, "available_models", return_value=[]):
        assert model_service.list_whisper_models(settings=Settings()) == []


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
@pytest.mark.parametrize("executable", [None, "/usr/bin/ollama"])
def test_ollama_status_unreachable_has_platform_action(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    executable: str | None,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    with (
        patch.object(ollama, "Client") as factory,
        patch.object(shutil, "which", return_value=executable) as which,
    ):
        factory.return_value.__enter__.return_value.list.side_effect = ConnectionError(
            "refused"
        )
        result = model_service.ollama_status(host=HOST)
    assert result["status"] == ("not_running" if executable else "not_installed")
    assert result["models"] == []
    expected = (
        "ollama.com"
        if executable is None
        else ("ollama serve" if platform == "linux" else "app Ollama")
    )
    assert expected in str(result["message"])
    which.assert_called_once_with("ollama")
    factory.assert_called_once_with(
        host=HOST, timeout=model_service.OLLAMA_STATUS_TIMEOUT
    )


@pytest.mark.parametrize("models", [[], [{"model": "qwen3.5:9b", "size": 1024}]])
def test_ollama_status_ready_without_local_executable(
    models: list[dict[str, str | int]],
) -> None:
    response = ollama.ListResponse.model_validate({"models": models})
    with (
        patch.object(ollama, "Client") as factory,
        patch.object(shutil, "which", return_value=None),
    ):
        factory.return_value.__enter__.return_value.list.return_value = response
        result = model_service.ollama_status(host=HOST)
    assert result == {
        "status": "ready",
        "message": "Ollama è pronto.",
        "models": [{**model, "parameter_size": None} for model in models],
    }
    factory.return_value.__exit__.assert_called_once()


def test_ollama_status_reports_parameter_size() -> None:
    response = ollama.ListResponse.model_validate(
        {
            "models": [
                {
                    "model": "qwen3.5:9b",
                    "size": 1024,
                    "details": {"parameter_size": "9.7B"},
                }
            ]
        }
    )
    with patch.object(ollama, "Client") as factory:
        factory.return_value.__enter__.return_value.list.return_value = response
        result = model_service.ollama_status(host=HOST)
    assert result["models"] == [
        {"model": "qwen3.5:9b", "size": 1024, "parameter_size": "9.7B"}
    ]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timeout"),
        ollama.ResponseError("unavailable", status_code=503),
    ],
)
def test_ollama_status_client_failure_returns_message_and_logs(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch.object(ollama, "Client") as factory,
        patch.object(shutil, "which", return_value="ollama"),
    ):
        factory.return_value.__enter__.return_value.list.side_effect = error
        result = model_service.ollama_status(host=HOST)
    assert result["status"] == "not_running"
    assert str(result["message"]).startswith("Ollama non è disponibile.")
    assert "Ollama" in caplog.text


def test_is_whisper_model_cached_true_when_in_local_cache(tmp_path: Path) -> None:
    with patch.object(model_service, "download_model", return_value=str(tmp_path)):
        assert model_service.is_whisper_model_cached(name="tiny") is True


def test_is_whisper_model_cached_false_when_missing_locally() -> None:
    with patch.object(
        model_service,
        "download_model",
        side_effect=LocalEntryNotFoundError("missing"),
    ):
        assert model_service.is_whisper_model_cached(name="tiny") is False
