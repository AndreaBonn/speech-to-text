import logging
from dataclasses import replace
from pathlib import Path

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness
from semantic_index_fixtures import STATUS_URL, SemanticHarness, semantic_harness
from vector_reconcile_fixtures import write_course

from sbobina.web import embedding_queue
from sbobina.web.embedding_store import (
    EMBEDDING_FILENAME,
    EmbeddingRun,
    EmbeddingStatus,
    create_embed,
    load_embed,
    save_embed,
)
from sbobina.web.embedding_supervisor import submit_embed_item

__all__ = ["embedding_harness", "semantic_harness"]

CORRUPT_RECORD = '{"status": "running"'


def test_recovery_quarantines_unreadable_record_and_unblocks_course(
    embedding_harness: EmbeddingHarness, caplog: pytest.LogCaptureFixture
) -> None:
    harness = embedding_harness
    record_path = harness.course_dir / EMBEDDING_FILENAME
    record_path.write_text(CORRUPT_RECORD, encoding="utf-8")

    harness.supervisor.recover_on_boot()

    assert not record_path.exists()
    quarantined = list(harness.course_dir.glob(f"{EMBEDDING_FILENAME}.corrupt-*"))
    assert [path.read_text(encoding="utf-8") for path in quarantined] == [
        CORRUPT_RECORD
    ]
    assert "Unreadable embedding run" in caplog.text
    run, _ = submit_embed_item(store=harness.store, course_id=harness.course_dir.name)
    assert run.status is EmbeddingStatus.QUEUED


def test_recovery_write_failure_logs_error_and_keeps_record(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = embedding_harness
    running = replace(
        create_embed(course_dir=harness.course_dir), status=EmbeddingStatus.RUNNING
    )
    save_embed(course_dir=harness.course_dir, record=running)

    def disk_full(**kwargs: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(embedding_queue, "save_embed", disk_full)
    with caplog.at_level(logging.ERROR):
        harness.supervisor.recover_on_boot()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "until the next start" in errors[-1].getMessage()
    assert harness.record().status is EmbeddingStatus.RUNNING


def test_status_reports_unreadable_run_instead_of_failing(
    semantic_harness: SemanticHarness,
) -> None:
    h = semantic_harness
    broken = write_course(store=h.store, label="Rotto")
    healthy = write_course(store=h.store, label="Sano")
    (h.store.courses_dir / broken.id / EMBEDDING_FILENAME).write_text(
        CORRUPT_RECORD, encoding="utf-8"
    )
    create_embed(course_dir=h.store.courses_dir / healthy.id)

    response = h.client.get(STATUS_URL)

    assert response.status_code == 200
    courses = {course["key"]: course for course in response.json()["data"]["courses"]}
    assert courses["rotto"]["run"] == {"status": "unreadable"}
    assert courses["rotto"]["queued_action"] is None
    assert courses["sano"]["run"]["status"] == "queued"
    assert load_embed(course_dir=h.store.courses_dir / healthy.id) is not None


def test_recovery_survives_record_removed_during_scan(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = embedding_harness
    other = write_course(store=harness.store, label="Altro")
    other_dir = harness.store.courses_dir / other.id
    create_embed(course_dir=harness.course_dir)
    create_embed(course_dir=other_dir)

    def load_then_vanish(*, course_dir: Path) -> EmbeddingRun | None:
        record = load_embed(course_dir=course_dir)
        if course_dir == harness.course_dir:
            (course_dir / EMBEDDING_FILENAME).unlink()
        return record

    monkeypatch.setattr(embedding_queue, "load_embed", load_then_vanish)
    queued = embedding_queue.recover_embed_runs(courses_dir=harness.store.courses_dir)

    assert [item.course_id for _, item in queued] == [other.id]
    assert "Embedding run vanished" in caplog.text
