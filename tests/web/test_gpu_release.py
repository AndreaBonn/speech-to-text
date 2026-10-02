import logging
from pathlib import Path
from unittest.mock import Mock

import httpx
import ollama
import pytest

from sbobina.settings import Settings
from sbobina.web import app as app_module
from sbobina.web import gpu_release


@pytest.mark.parametrize("names", [[], ["qwen3.5:9b", "second:model"]])
def test_unload_ollama_models_loaded_models_releases_all(
    monkeypatch: pytest.MonkeyPatch, names: list[str]
) -> None:
    client = Mock()
    client.ps.return_value = ollama.ProcessResponse(
        models=[ollama.ProcessResponse.Model(model=name) for name in names]
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(ollama, "Client", factory)

    gpu_release.unload_ollama_models(host="http://ollama.test:11434")

    factory.assert_called_once_with(host="http://ollama.test:11434")
    assert client.generate.call_count == len(names)
    for name in names:
        client.generate.assert_any_call(model=name, keep_alive=0)


@pytest.mark.parametrize("method", ["ps", "generate"])
@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("offline"),
        ollama.ResponseError("server error"),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_unload_ollama_models_client_failure_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    error: Exception,
) -> None:
    client = Mock()
    client.ps.return_value = ollama.ProcessResponse(
        models=[ollama.ProcessResponse.Model(model="qwen3.5:9b")]
    )
    getattr(client, method).side_effect = error
    monkeypatch.setattr(ollama, "Client", Mock(return_value=client))

    with caplog.at_level(level=logging.WARNING):
        gpu_release.unload_ollama_models(host="http://ollama.test:11434")

    assert any(
        record.levelno == logging.WARNING and str(error) in record.getMessage()
        for record in caplog.records
    )


def test_create_app_before_transcribe_uses_configured_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = Mock()
    unload = Mock()
    monkeypatch.setattr(app_module, "Supervisor", factory)
    monkeypatch.setattr(app_module, "unload_ollama_models", unload, raising=False)

    app_module.create_app(
        settings=Settings(ollama_host="http://configured:11434"), data_dir=tmp_path
    )
    factory.call_args.kwargs["before_transcribe"]()

    unload.assert_called_once_with(host="http://configured:11434")


def test_unload_ollama_models_skips_entries_without_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.ps.return_value = ollama.ProcessResponse(
        models=[
            ollama.ProcessResponse.Model(model=None),
            ollama.ProcessResponse.Model(model="qwen3.5:9b"),
        ]
    )
    monkeypatch.setattr(ollama, "Client", Mock(return_value=client))

    gpu_release.unload_ollama_models(host="http://ollama.test:11434")

    client.generate.assert_called_once_with(model="qwen3.5:9b", keep_alive=0)
