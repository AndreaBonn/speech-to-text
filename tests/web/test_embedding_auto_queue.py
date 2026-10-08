from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness

from sbobina import ollama_embed
from sbobina.ollama_embed import EmbeddingUnavailableError, ModelStatus
from sbobina.settings import settings
from sbobina.web import course_actions, embedding_supervisor
from sbobina.web.embedding_store import EmbeddingStatus, load_embed, save_embed

__all__ = ["embedding_harness"]


def _enqueue(harness: EmbeddingHarness) -> None:
    embedding_supervisor.maybe_enqueue_embed(
        supervisor=harness.supervisor, course_id=harness.course_dir.name
    )


def _available(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def status(**kwargs: object) -> ModelStatus:
        calls.append(kwargs)
        return ModelStatus(digest="test", dimensions=2)

    monkeypatch.setattr(ollama_embed, "model_status", status)
    monkeypatch.setattr(settings, "semantic_search", True)
    return calls


def test_maybe_enqueue_embed_disabled_then_enabled_queues_once(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    calls = _available(monkeypatch=monkeypatch)
    monkeypatch.setattr(settings, "semantic_search", False)
    _enqueue(harness=harness)
    assert list(harness.supervisor._queue) == []
    assert load_embed(course_dir=harness.course_dir) is None
    assert calls == []
    monkeypatch.setattr(settings, "semantic_search", True)
    _enqueue(harness=harness)
    assert len(harness.supervisor._queue) == 1
    assert harness.record().status is EmbeddingStatus.QUEUED
    assert calls == [
        {
            "host": settings.ollama_host,
            "model": settings.embedding_model,
            "timeout_s": embedding_supervisor.ENQUEUE_PROBE_TIMEOUT_S,
        }
    ]


@pytest.mark.parametrize("reason", ["model_missing", "unreachable", "bad_response"])
def test_maybe_enqueue_embed_unavailable_persists_reason_then_recovers(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    harness = embedding_harness
    _available(monkeypatch=monkeypatch)

    def unavailable(**kwargs: object) -> ModelStatus:
        raise EmbeddingUnavailableError(reason=reason)

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    _enqueue(harness=harness)
    assert list(harness.supervisor._queue) == []
    assert harness.record().status is EmbeddingStatus.FAILED
    assert harness.record().error == reason
    assert (harness.record().processed, harness.record().total) == (0, 0)
    _available(monkeypatch=monkeypatch)
    _enqueue(harness=harness)
    assert len(harness.supervisor._queue) == 1
    assert harness.record().status is EmbeddingStatus.QUEUED


@pytest.mark.parametrize("status", [EmbeddingStatus.QUEUED, EmbeddingStatus.RUNNING])
def test_maybe_enqueue_embed_missing_preserves_pending_run(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
    status: EmbeddingStatus,
) -> None:
    harness = embedding_harness
    _available(monkeypatch=monkeypatch)
    _enqueue(harness=harness)
    record = replace(harness.record(), status=status)
    save_embed(course_dir=harness.course_dir, record=record)

    def unavailable(**kwargs: object) -> ModelStatus:
        raise EmbeddingUnavailableError(reason="model_missing")

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    _enqueue(harness=harness)
    assert harness.record() == record
    assert len(harness.supervisor._queue) == 1


def test_maybe_enqueue_embed_concurrent_submissions_queue_one(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    _available(monkeypatch=monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: _enqueue(harness=harness), range(8)))
    assert len(harness.supervisor._queue) == 1
    assert harness.record().status is EmbeddingStatus.QUEUED


def test_maybe_enqueue_embed_cancelled_course_is_queued_again(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    _available(monkeypatch=monkeypatch)
    _enqueue(harness=harness)
    course_actions.cancel_embed(supervisor=harness.supervisor, course_key="diritto")
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert list(harness.supervisor._queue) == []

    _enqueue(harness=harness)
    assert harness.record().status is EmbeddingStatus.QUEUED
    assert len(harness.supervisor._queue) == 1


def test_maybe_enqueue_embed_unexpected_error_is_logged_not_raised(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = embedding_harness
    monkeypatch.setattr(settings, "semantic_search", True)

    def broken(**kwargs: object) -> ModelStatus:
        raise RuntimeError("unexpected client failure")

    monkeypatch.setattr(ollama_embed, "model_status", broken)
    _enqueue(harness=harness)

    assert "Automatic embedding enqueue failed" in caplog.text
    assert caplog.records[-1].exc_info is not None
    assert list(harness.supervisor._queue) == []
    _available(monkeypatch=monkeypatch)
    _enqueue(harness=harness)
    assert len(harness.supervisor._queue) == 1


def test_unavailable_enqueue_preserves_last_successful_indexing(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    _available(monkeypatch=monkeypatch)
    _enqueue(harness=harness)
    timestamp = datetime(2026, 10, 8, tzinfo=UTC)
    record = replace(
        harness.record(), status=EmbeddingStatus.DONE, last_indexed_at=timestamp
    )
    save_embed(course_dir=harness.course_dir, record=record)

    def unavailable(**kwargs: object) -> ModelStatus:
        raise EmbeddingUnavailableError(reason="unreachable")

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    _enqueue(harness=harness)
    assert harness.record().status is EmbeddingStatus.FAILED
    assert harness.record().last_indexed_at == timestamp
