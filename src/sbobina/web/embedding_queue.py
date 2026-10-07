import logging
from dataclasses import replace
from pathlib import Path

from sbobina.web.embedding_store import (
    EMBEDDING_FILENAME,
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
            if record is None:
                continue
            if record.status is EmbeddingStatus.RUNNING:
                save_embed(
                    course_dir=path.parent,
                    record=replace(
                        record,
                        status=EmbeddingStatus.CANCELLED,
                    ),
                )
            elif record.status is EmbeddingStatus.QUEUED:
                item = WorkItem(
                    job_id=path.parent.name,
                    action="embed",
                    course_id=path.parent.name,
                )
                queued.append((path.stat().st_mtime, item))
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Cannot recover embedding run %s: %s", path, error)
    return queued
