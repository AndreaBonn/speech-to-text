from unittest.mock import Mock

import pytest
from semantic_index_fixtures import BACKFILL_URL, SemanticHarness, semantic_harness
from vector_reconcile_fixtures import write_course

from sbobina.web import embedding_backfill
from sbobina.web.embedding_store import EmbeddingRun, EmbeddingStatus, load_embed
from sbobina.web.embedding_supervisor import submit_embed_item
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore

__all__ = ["semantic_harness"]


def test_backfill_scan_failure_queues_nothing(
    semantic_harness: SemanticHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = semantic_harness
    first = write_course(store=h.store, label="First")
    second = write_course(store=h.store, label="Second")
    monkeypatch.setattr(
        embedding_backfill, "iter_courses", lambda **kw: [first, second]
    )
    monkeypatch.setattr(
        embedding_backfill,
        "count_missing_units",
        Mock(side_effect=[1, OSError("private path")]),
    )
    response = h.client.post(BACKFILL_URL, json={"confirm_model_change": False})
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "BACKFILL_FAILED",
        "message": "Lettura dei corsi non riuscita: nessun corso accodato",
    }
    assert list(h.supervisor._queue) == []
    assert load_embed(course_dir=h.store.courses_dir / first.id) is None


def test_backfill_enqueue_failure_keeps_persisted_items_in_live_queue(
    semantic_harness: SemanticHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = semantic_harness
    first = write_course(store=h.store, label="First")
    second = write_course(store=h.store, label="Second")
    monkeypatch.setattr(
        embedding_backfill, "iter_courses", lambda **kw: [first, second]
    )
    monkeypatch.setattr(embedding_backfill, "count_missing_units", Mock(return_value=1))
    calls: list[str] = []

    def submit(*, store: JobStore, course_key: str) -> tuple[EmbeddingRun, WorkItem]:
        calls.append(course_key)
        if len(calls) == 2:
            raise OSError("disk full")
        return submit_embed_item(store=store, course_key=course_key)

    monkeypatch.setattr(embedding_backfill, "submit_embed_item", submit)
    response = h.client.post(BACKFILL_URL, json={"confirm_model_change": False})
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "BACKFILL_FAILED",
        "message": "Accodamento interrotto: i corsi già accodati restano in elaborazione",
    }
    assert [item.course_id for item in h.supervisor._queue] == [first.id]
    record = load_embed(course_dir=h.store.courses_dir / first.id)
    assert record is not None and record.status is EmbeddingStatus.QUEUED
