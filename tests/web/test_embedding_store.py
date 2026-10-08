from dataclasses import replace
from pathlib import Path

import pytest

from sbobina.web.embedding_store import (
    EmbeddingRun,
    EmbeddingStatus,
    create_embed,
    finish_embed,
    load_embed,
    save_embed,
)


def test_create_embed_persists_queued_course_record(tmp_path: Path) -> None:
    course_dir = tmp_path / "courses" / "course"
    assert load_embed(course_dir=course_dir) is None
    record = create_embed(course_dir=course_dir)
    assert record == EmbeddingRun(
        status=EmbeddingStatus.QUEUED, processed=0, total=0, error=None
    )
    assert load_embed(course_dir=course_dir) == record
    assert (course_dir / "embedding.json").is_file()


@pytest.mark.parametrize("status", list(EmbeddingStatus))
def test_save_embed_roundtrips_state_and_progress(
    tmp_path: Path, status: EmbeddingStatus
) -> None:
    record = EmbeddingRun(
        status=status,
        processed=32,
        total=40,
        error="STAGE_FAILED" if status == EmbeddingStatus.FAILED else None,
    )
    save_embed(course_dir=tmp_path, record=record)
    assert load_embed(course_dir=tmp_path) == record


@pytest.mark.parametrize("processed,total", [(-1, 2), (1, -1), (3, 2)])
def test_embedding_run_rejects_invalid_progress(processed: int, total: int) -> None:
    with pytest.raises(ValueError, match="progress"):
        EmbeddingRun(
            status=EmbeddingStatus.RUNNING, processed=processed, total=total, error=None
        )


@pytest.mark.parametrize("processed,total", [(0, 0), (0, 2), (2, 2)])
def test_embedding_run_boundary_progress_is_accepted(
    processed: int, total: int
) -> None:
    record = EmbeddingRun(
        status=EmbeddingStatus.RUNNING, processed=processed, total=total, error=None
    )
    assert (record.processed, record.total) == (processed, total)


def test_embedding_run_reserves_error_for_failure() -> None:
    with pytest.raises(ValueError, match="error"):
        EmbeddingRun(status=EmbeddingStatus.FAILED, processed=0, total=0, error=None)
    with pytest.raises(ValueError, match="error"):
        EmbeddingRun(status=EmbeddingStatus.DONE, processed=0, total=0, error="bad")


def test_finish_embed_preserves_progress_and_cancelled_state(tmp_path: Path) -> None:
    record = EmbeddingRun(
        status=EmbeddingStatus.RUNNING, processed=32, total=40, error=None
    )
    save_embed(course_dir=tmp_path, record=record)
    finish_embed(course_dir=tmp_path, status=EmbeddingStatus.FAILED, error="crash")
    assert load_embed(course_dir=tmp_path) == replace(
        record, status=EmbeddingStatus.FAILED, error="crash"
    )
    cancelled = replace(record, status=EmbeddingStatus.CANCELLED)
    save_embed(course_dir=tmp_path, record=cancelled)
    finish_embed(course_dir=tmp_path, status=EmbeddingStatus.FAILED, error="crash")
    assert load_embed(course_dir=tmp_path) == cancelled
