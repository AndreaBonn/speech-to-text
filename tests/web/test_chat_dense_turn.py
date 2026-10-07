import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from chat_api_fixtures import ANSWER
from hybrid_runtime_fixtures import indexed_runtime
from study_fixtures import QUOTE
from vector_reconcile_fixtures import write_course, write_lecture

from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.web.chat_records import ChatAnswerRecord
from sbobina.web.chat_store import create_chat, load_records
from sbobina.web.chat_turn import ChatLocation, ChatServices, ask
from sbobina.web.dense_factory import DenseRuntime
from sbobina.web.embedding_supervisor import EMBEDDING_STAGE
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.job_store import JobStore


@pytest.fixture
def turn(tmp_path: Path) -> tuple[ChatServices, ChatLocation]:
    store = JobStore(data_dir=tmp_path)
    course = write_course(store=store)
    write_lecture(store=store, texts=[QUOTE])
    chat = create_chat(courses_dir=store.courses_dir, course_id=course.id)
    return (
        ChatServices(
            store=store,
            index_path=tmp_path / "search.sqlite3",
            arbiter=GpuArbiter(),
            chat_client=lambda request: ANSWER,
            model="fake",
        ),
        ChatLocation(key=course.key, course_id=course.id, chat_id=chat.id),
    )


def test_turn_persists_missing_reason_once_then_logs_another_reason(
    turn: tuple[ChatServices, ChatLocation],
    caplog: pytest.LogCaptureFixture,
) -> None:
    services, where = turn
    with caplog.at_level(logging.WARNING):
        for reason in ("model_missing",) * 3 + ("unreachable",):
            configured = replace(
                services, dense=DenseRuntime(reason=reason, model="qwen3-embedding:8b")
            )
            result = ask(
                services=configured, where=where, records=[], question="causa contratto"
            )
            assert result.retrieval_mode == {"mode": "bm25", "reason": reason}
            assert len(result.sentences) == 1
    records = load_records(
        courses_dir=services.store.courses_dir,
        course_id=where.course_id,
        chat_id=where.chat_id,
    )
    answers = [item for item in records if isinstance(item, ChatAnswerRecord)]
    assert len(answers) == 4 and answers[0].retrieval_mode == {
        "mode": "bm25",
        "reason": "model_missing",
    }
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and all("qwen3-embedding:8b" in item for item in warnings)


def test_api_turn_queries_cpu_while_transcription_holds_lease(
    turn: tuple[ChatServices, ChatLocation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, where = turn
    dense, client = indexed_runtime(store=services.store)
    lease = Mock(side_effect=AssertionError("dense API requested a GPU lease"))
    monkeypatch.setattr(services.arbiter, "chat_turn", lease)
    services = replace(services, dense=dense, guard_whole_client=False)
    with services.arbiter.transcription_lease(stage="TRANSCRIBING"):
        result = ask(
            services=services, where=where, records=[], question="causa contratto"
        )
    assert (
        result.retrieval_mode is not None and result.retrieval_mode["mode"] == "dense"
    )
    assert len(result.sentences) == 1 and client.calls[0]["options"]["num_gpu"] == 0
    assert lease.call_count == 0


def test_local_turn_queries_before_chat_lease(
    turn: tuple[ChatServices, ChatLocation],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, where = turn
    dense, client = indexed_runtime(store=services.store)
    original = services.arbiter.chat_turn
    events: list[str] = []

    @contextmanager
    def guarded() -> Iterator[None]:
        assert len(client.calls) == 1
        events.append("lease")
        with original():
            yield

    monkeypatch.setattr(
        services.arbiter, "chat_turn", Mock(side_effect=[original(), guarded()])
    )
    result = ask(
        services=replace(services, dense=dense),
        where=where,
        records=[],
        question="causa",
    )
    assert (
        result.retrieval_mode is not None and result.retrieval_mode["mode"] == "dense"
    )
    assert events == ["lease"] and len(result.sentences) == 1


def test_ranker_query_failure_warns_once_across_turns(
    turn: tuple[ChatServices, ChatLocation],
    caplog: pytest.LogCaptureFixture,
) -> None:
    services, where = turn
    dense, client = indexed_runtime(store=services.store)
    client.failure = EmbeddingUnavailableError(reason="unreachable")
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            result = ask(
                services=replace(services, dense=dense),
                where=where,
                records=[],
                question="causa",
            )
            assert (
                result.retrieval_mode is not None
                and result.retrieval_mode["reason"] == "unreachable"
            )
            assert len(result.sentences) == 1
    assert len(client.calls) == 3
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_api_turn_during_indexing_returns_bm25_without_embedding(
    turn: tuple[ChatServices, ChatLocation],
) -> None:
    services, where = turn
    dense, client = indexed_runtime(store=services.store)
    services = replace(services, dense=dense, guard_whole_client=False)
    with services.arbiter.transcription_lease(stage=EMBEDDING_STAGE):
        result = ask(
            services=services, where=where, records=[], question="causa contratto"
        )
    assert result.retrieval_mode is not None and result.retrieval_mode["mode"] == "bm25"
    assert result.retrieval_mode["reason"] == "gpu_busy"
    assert len(result.sentences) == 1
    assert client.calls == []
