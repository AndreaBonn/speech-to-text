from pathlib import Path

import pytest
from chat_api_fixtures import ANSWER
from hybrid_runtime_fixtures import enable_factory, indexed_runtime
from starlette.requests import Request
from study_fixtures import QUOTE
from vector_reconcile_fixtures import write_course, write_lecture

from sbobina.settings import Settings
from sbobina.web.api_chat import (
    ChatMessageBody,
    _services,
    create_chat_route,
    get_chat_route,
    post_message_route,
)
from sbobina.web.app import create_app
from sbobina.web.embedding_supervisor import EMBEDDING_STAGE


@pytest.fixture
def request_context(tmp_path: Path) -> Request:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    app.state.chat_client = lambda request: ANSWER
    write_course(store=app.state.job_store)
    write_lecture(store=app.state.job_store, texts=[QUOTE])
    return Request(scope={"type": "http", "app": app})


def test_api_wiring_exposes_missing_reason_in_reply_and_history(
    request_context: Request,
) -> None:
    services = _services(request=request_context)
    chat_id = create_chat_route(key="diritto", services=services)["data"]["id"]
    result = post_message_route(
        key="diritto",
        chat_id=chat_id,
        body=ChatMessageBody(question="causa"),
        services=services,
    )
    stored = get_chat_route(key="diritto", chat_id=chat_id, services=services)
    expected = {"mode": "bm25", "reason": "model_missing"}
    assert result["data"]["outcome"] == "DONE"
    assert result["data"]["retrieval_mode"] == expected
    assert stored["data"]["messages"][-1]["retrieval_mode"] == expected


def test_api_wiring_builds_dense_and_skips_gpu_lease_for_api_engine(
    request_context: Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=request_context.app.state.job_store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")
    monkeypatch.setattr(request_context.app.state.settings, "llm_engine", "api")
    services = _services(request=request_context)
    chat_id = create_chat_route(key="diritto", services=services)["data"]["id"]
    with services.arbiter.transcription_lease(stage="TRANSCRIBING"):
        result = post_message_route(
            key="diritto",
            chat_id=chat_id,
            body=ChatMessageBody(question="causa"),
            services=services,
        )
    assert result["data"]["outcome"] == "DONE"
    assert result["data"]["retrieval_mode"]["mode"] == "dense"
    assert client.calls[0]["options"]["num_gpu"] == 0


def test_api_wiring_during_indexing_returns_bm25_without_embedding(
    request_context: Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=request_context.app.state.job_store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")
    monkeypatch.setattr(request_context.app.state.settings, "llm_engine", "api")
    services = _services(request=request_context)
    chat_id = create_chat_route(key="diritto", services=services)["data"]["id"]
    with services.arbiter.transcription_lease(stage=EMBEDDING_STAGE):
        result = post_message_route(
            key="diritto",
            chat_id=chat_id,
            body=ChatMessageBody(question="causa"),
            services=services,
        )
    assert result["data"]["outcome"] == "DONE"
    assert result["data"]["retrieval_mode"]["mode"] == "bm25"
    assert result["data"]["retrieval_mode"]["reason"] == "gpu_busy"
    assert client.calls == []
