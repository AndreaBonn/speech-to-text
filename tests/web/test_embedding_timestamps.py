import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sbobina.web.embedding_store import (
    EmbeddingStatus,
    create_embed,
    finish_embed,
    load_embed,
    save_embed,
)


def test_success_timestamp_survives_requeue_and_failure(tmp_path: Path) -> None:
    record = create_embed(course_dir=tmp_path)
    save_embed(
        course_dir=tmp_path, record=replace(record, status=EmbeddingStatus.RUNNING)
    )
    before = datetime.now(tz=UTC)
    finish_embed(course_dir=tmp_path, status=EmbeddingStatus.DONE)
    completed = load_embed(course_dir=tmp_path)
    assert completed is not None and completed.last_indexed_at is not None
    assert before <= completed.last_indexed_at <= datetime.now(tz=UTC)
    queued = create_embed(course_dir=tmp_path)
    assert queued.last_indexed_at == completed.last_indexed_at
    save_embed(
        course_dir=tmp_path, record=replace(queued, status=EmbeddingStatus.RUNNING)
    )
    finish_embed(course_dir=tmp_path, status=EmbeddingStatus.FAILED, error="failure")
    failed = load_embed(course_dir=tmp_path)
    assert failed is not None and failed.last_indexed_at == completed.last_indexed_at


def test_legacy_embedding_record_has_unknown_success_time(tmp_path: Path) -> None:
    (tmp_path / "embedding.json").write_text(
        json.dumps({"status": "done", "processed": 1, "total": 1, "error": None}),
        encoding="utf-8",
    )
    record = load_embed(course_dir=tmp_path)
    assert record is not None and record.status == EmbeddingStatus.DONE
    assert record.last_indexed_at is None
