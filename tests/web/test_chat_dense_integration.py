import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import Mock

import pytest
from chat_api_fixtures import CHATS_URL, ChatApp
from fastapi import FastAPI
from hybrid_runtime_fixtures import enable_factory, indexed_runtime

from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.web import dense_factory
from sbobina.web.embedding_supervisor import EMBEDDING_STAGE

pytest_plugins = ["chat_api_fixtures"]


def test_three_missing_model_turns_persist_reason_and_warn_once(
    chat_app: ChatApp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chat_id = chat_app.new_chat()
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            response = chat_app.ask(chat_id=chat_id)
            assert response.status_code == 200
            assert response.json()["data"]["retrieval_mode"] == {
                "mode": "bm25",
                "reason": "model_missing",
            }
    answers = [
        line for line in chat_app.lines(chat_id=chat_id) if line["kind"] == "answer"
    ]
    assert [item["retrieval_mode"] for item in answers] == [
        {"mode": "bm25", "reason": "model_missing"}
    ] * 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "qwen3-embedding:8b" in warnings[0].getMessage()
    stored = chat_app.client.get(f"{CHATS_URL}/{chat_id}").json()["data"]
    assert stored["messages"][-1]["retrieval_mode"] == answers[-1]["retrieval_mode"]


def test_distinct_degradation_reason_warns_again(
    chat_app: ChatApp,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chat_id = chat_app.new_chat()
    with caplog.at_level(logging.WARNING):
        assert chat_app.ask(chat_id=chat_id).status_code == 200
        monkeypatch.setattr(
            dense_factory,
            "model_status",
            Mock(
                side_effect=EmbeddingUnavailableError(reason="unreachable"),
            ),
        )
        response = chat_app.ask(chat_id=chat_id)
    assert response.json()["data"]["retrieval_mode"]["reason"] == "unreachable"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "model_missing" in warnings[0] and "unreachable" in warnings[1]


def test_api_dense_query_succeeds_during_transcription_without_lease(
    chat_app: ChatApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=chat_app.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")
    app = cast(FastAPI, chat_app.client.app)
    monkeypatch.setattr(app.state.settings, "llm_engine", "api")
    lease = Mock(side_effect=AssertionError("API dense query requested GPU lease"))
    monkeypatch.setattr(chat_app.arbiter, "chat_turn", lease)
    chat_id = chat_app.new_chat()
    with chat_app.arbiter.transcription_lease(stage="TRANSCRIBING"):
        response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 200
    assert response.json()["data"]["outcome"] == "DONE"
    assert response.json()["data"]["retrieval_mode"]["mode"] == "dense"
    assert client.calls[0]["options"]["num_gpu"] == 0
    assert lease.call_count == 0


def test_local_dense_query_finishes_before_chat_lease(
    chat_app: ChatApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=chat_app.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    original = chat_app.arbiter.chat_turn
    events: list[str] = []

    @contextmanager
    def guarded() -> Iterator[None]:
        assert len(client.calls) == 1
        events.append("lease")
        with original():
            yield

    monkeypatch.setattr(
        chat_app.arbiter, "chat_turn", Mock(side_effect=[original(), guarded()])
    )
    response = chat_app.ask(chat_id=chat_app.new_chat())
    assert response.status_code == 200
    assert response.json()["data"]["retrieval_mode"]["mode"] == "dense"
    assert events == ["lease"] and client.calls[0]["options"]["num_gpu"] == 0


def test_query_failure_warning_is_shared_with_reporter(
    chat_app: ChatApp,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, client = indexed_runtime(store=chat_app.store)
    client.failure = EmbeddingUnavailableError(reason="unreachable")
    enable_factory(monkeypatch=monkeypatch, client=client)
    chat_id = chat_app.new_chat()
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            response = chat_app.ask(chat_id=chat_id)
            assert response.status_code == 200
            assert response.json()["data"]["retrieval_mode"]["reason"] == "unreachable"
    assert len(client.calls) == 3
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_api_dense_query_during_indexing_returns_bm25_without_embedding(
    chat_app: ChatApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=chat_app.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")
    app = cast(FastAPI, chat_app.client.app)
    monkeypatch.setattr(app.state.settings, "llm_engine", "api")
    chat_id = chat_app.new_chat()
    with chat_app.arbiter.transcription_lease(stage=EMBEDDING_STAGE):
        response = chat_app.ask(chat_id=chat_id)
    assert response.status_code == 200
    assert response.json()["data"]["outcome"] == "DONE"
    assert response.json()["data"]["retrieval_mode"]["mode"] == "bm25"
    assert response.json()["data"]["retrieval_mode"]["reason"] == "gpu_busy"
    assert client.calls == []
