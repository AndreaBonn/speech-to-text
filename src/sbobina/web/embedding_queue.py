import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sbobina.web.embedding_store import (
    EMBEDDING_FILENAME,
    EmbeddingRun,
    EmbeddingStatus,
    load_embed,
    save_embed,
)
from sbobina.web.job_models import WorkItem

logger = logging.getLogger(__name__)


def recover_embed_runs(courses_dir: Path) -> list[tuple[float, WorkItem]]:
    queued: list[tuple[float, WorkItem]] = []
    for path in courses_dir.glob(f"*/{EMBEDDING_FILENAME}"):
        try:
            record = load_embed(course_dir=path.parent)
        except (OSError, ValueError, KeyError, TypeError) as error:
            _quarantine(path=path, error=error)
            continue
        if record is None:
            continue
        if record.status is EmbeddingStatus.RUNNING:
            _cancel_orphan(path=path, record=record)
        elif record.status is EmbeddingStatus.QUEUED:
            queued.extend(_queued_item(path=path))
    return queued


def _queued_item(path: Path) -> list[tuple[float, WorkItem]]:
    try:
        queued_at = path.stat().st_mtime
    except OSError:
        # The course was deleted between the scan and this read: nothing to queue,
        # and the other courses must still be recovered.
        logger.warning("Embedding run vanished during recovery: %s", path)
        return []
    item = WorkItem(job_id=path.parent.name, action="embed", course_id=path.parent.name)
    return [(queued_at, item)]


def _quarantine(path: Path, error: Exception) -> None:
    # An unreadable record makes every later load raise, which would block the
    # course for good: move it aside so the course can be queued again.
    # Timestamped, so an earlier quarantined record is kept as evidence.
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%f")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(target)
    except OSError:
        logger.exception("Cannot move aside unreadable embedding run %s", path)
        return
    logger.warning("Unreadable embedding run %s moved to %s: %s", path, target, error)


def _cancel_orphan(path: Path, record: EmbeddingRun) -> None:
    try:
        save_embed(
            course_dir=path.parent,
            record=replace(record, status=EmbeddingStatus.CANCELLED),
        )
    except OSError:
        logger.exception(
            "Cannot cancel orphaned embedding run %s: the course stays marked "
            "running until the next start",
            path,
        )
