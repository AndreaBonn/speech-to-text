"""Queue-side transitions for the "generation" WorkItem.

Mirrors work_items.py's role for pipeline/study, but GenerationRecord has no
created_at/updated_at field: queued-recovery is ordered by the record file's
mtime instead of a timestamp field.
"""

from dataclasses import replace
from pathlib import Path

from sbobina.generation_models import GenerationRecord, GenerationStatus
from sbobina.web.errors import JobNotCancellableError
from sbobina.web.generation_store import (
    generation_path,
    iter_generations,
    load_generation,
    save_generation,
)
from sbobina.web.job_models import WorkItem


def transition_generation(
    record: GenerationRecord, status: GenerationStatus, error: str | None = None
) -> GenerationRecord:
    return replace(record, status=status, error=error)


def recover_generations(courses_dir: Path) -> list[tuple[float, WorkItem]]:
    """Interrupt running generations in place; return queued ones, with the
    record file's mtime as the sort key for the supervisor to merge in."""
    queued: list[tuple[float, WorkItem]] = []
    for course_id, record in iter_generations(courses_dir=courses_dir):
        if record.status == GenerationStatus.RUNNING:
            # Unlike JobRecord, GenerationRecord.error is reserved for FAILED
            # (generation_models.py's __post_init__ rejects it on INTERRUPTED).
            save_generation(
                courses_dir=courses_dir,
                course_id=course_id,
                record=transition_generation(
                    record=record, status=GenerationStatus.INTERRUPTED
                ),
            )
        elif record.status == GenerationStatus.QUEUED:
            path = generation_path(
                courses_dir=courses_dir, course_id=course_id, gen_id=record.id
            )
            item = WorkItem(job_id=record.id, action="generation", course_id=course_id)
            queued.append((path.stat().st_mtime, item))
    return queued


def require_cancellable(
    courses_dir: Path, course_id: str, gen_id: str
) -> GenerationRecord:
    record = load_generation(
        courses_dir=courses_dir, course_id=course_id, gen_id=gen_id
    )
    if record.status not in (GenerationStatus.QUEUED, GenerationStatus.RUNNING):
        raise JobNotCancellableError(job_id=gen_id)
    return record


def cancel_generation_action(
    courses_dir: Path, course_id: str, gen_id: str
) -> GenerationRecord:
    record = require_cancellable(
        courses_dir=courses_dir, course_id=course_id, gen_id=gen_id
    )
    updated = transition_generation(record=record, status=GenerationStatus.INTERRUPTED)
    save_generation(courses_dir=courses_dir, course_id=course_id, record=updated)
    return updated


def finish_generation(
    courses_dir: Path,
    course_id: str,
    gen_id: str,
    status: GenerationStatus,
    error: str | None = None,
) -> None:
    record = load_generation(
        courses_dir=courses_dir, course_id=course_id, gen_id=gen_id
    )
    if record.status == GenerationStatus.RUNNING:
        save_generation(
            courses_dir=courses_dir,
            course_id=course_id,
            record=transition_generation(record=record, status=status, error=error),
        )
