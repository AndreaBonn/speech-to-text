from typing import cast

import pytest
from chat_api_fixtures import ChatApp, chat_app
from fastapi import FastAPI
from hybrid_runtime_fixtures import enable_factory, indexed_runtime

from sbobina.settings import Settings
from sbobina.web.embedding_supervisor import EMBEDDING_STAGE

__all__ = ["chat_app"]


def test_local_chat_during_embedding_returns_stage_estimate_and_label(
    chat_app: ChatApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = indexed_runtime(store=chat_app.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    chat_id = chat_app.new_chat()
    with chat_app.arbiter.transcription_lease(stage="embedding", estimate_s=20.0):
        response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "GPU_BUSY"
    assert "indicizzazione semantica" in error["message"]
    assert {"field": "stage", "message": "embedding"} in error["details"]
    assert {"field": "estimate_s", "message": "20.0"} in error["details"]
    assert client.calls == []
    response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 200
    assert response.json()["data"]["retrieval_mode"]["mode"] == "dense"
    assert len(client.calls) == 1


def test_api_chat_during_writer_uses_bm25_then_recovers_dense(
    chat_app: ChatApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    cast(FastAPI, chat_app.client.app).state.settings = Settings(llm_engine="api")
    _, client = indexed_runtime(store=chat_app.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    chat_id = chat_app.new_chat()
    with chat_app.arbiter.transcription_lease(stage=EMBEDDING_STAGE, estimate_s=20.0):
        response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["retrieval_mode"]["mode"] == "bm25"
    assert payload["retrieval_mode"]["reason"] == "gpu_busy"
    assert len(payload["sentences"]) == 1 and client.calls == []
    response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 200
    assert response.json()["data"]["retrieval_mode"]["mode"] == "dense"
    assert len(client.calls) == 1
