"""Queue-side transitions for the "ocr" WorkItem.

Mirrors generation_queue.py's role for "generation". OcrRun has no
created_at/updated_at either: queued-recovery is ordered by ocr.json's mtime.
"""

from dataclasses import replace
from pathlib import Path

from sbobina.document_models import DocumentStatus
from sbobina.web.document_store import read_document
from sbobina.web.errors import JobNotCancellableError, NotFoundError
from sbobina.web.job_models import WorkItem
from sbobina.web.ocr_store import (
    OcrRun,
    OcrStatus,
    iter_ocr_runs,
    load_ocr,
    ocr_path,
    save_ocr,
)


def transition_ocr(
    record: OcrRun, status: OcrStatus, error: str | None = None
) -> OcrRun:
    return replace(record, status=status, error=error)


def _recovered_status(courses_dir: Path, course_id: str, doc_id: str) -> OcrStatus:
    """DONE when the child crashed after writing the text, else INTERRUPTED.

    The runner writes text.json and the READY document before marking the
    run done: a READY document means the OCR result is already in place.
    """
    try:
        document = read_document(
            courses_dir=courses_dir, course_id=course_id, doc_id=doc_id
        )
    except (OSError, ValueError, NotFoundError):
        return OcrStatus.INTERRUPTED
    if document.status is DocumentStatus.READY:
        return OcrStatus.DONE
    return OcrStatus.INTERRUPTED


def recover_ocr_runs(courses_dir: Path) -> list[tuple[float, WorkItem]]:
    """Interrupt running OCR runs in place; return queued ones, with the
    record file's mtime as the sort key for the supervisor to merge in."""
    queued: list[tuple[float, WorkItem]] = []
    for course_id, doc_id, record in iter_ocr_runs(courses_dir=courses_dir):
        if record.status == OcrStatus.RUNNING:
            save_ocr(
                courses_dir=courses_dir,
                course_id=course_id,
                doc_id=doc_id,
                record=transition_ocr(
                    record=record,
                    status=_recovered_status(
                        courses_dir=courses_dir, course_id=course_id, doc_id=doc_id
                    ),
                ),
            )
        elif record.status == OcrStatus.QUEUED:
            path = ocr_path(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
            item = WorkItem(job_id=doc_id, action="ocr", course_id=course_id)
            queued.append((path.stat().st_mtime, item))
    return queued


def require_cancellable(courses_dir: Path, course_id: str, doc_id: str) -> OcrRun:
    record = load_ocr(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    if record is None or record.status not in (OcrStatus.QUEUED, OcrStatus.RUNNING):
        raise JobNotCancellableError(job_id=doc_id)
    return record


def cancel_ocr_action(courses_dir: Path, course_id: str, doc_id: str) -> OcrRun:
    record = require_cancellable(
        courses_dir=courses_dir, course_id=course_id, doc_id=doc_id
    )
    updated = transition_ocr(record=record, status=OcrStatus.INTERRUPTED)
    save_ocr(
        courses_dir=courses_dir, course_id=course_id, doc_id=doc_id, record=updated
    )
    return updated


def finish_ocr(
    courses_dir: Path,
    course_id: str,
    doc_id: str,
    status: OcrStatus,
    error: str | None = None,
) -> None:
    record = load_ocr(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    if record is not None and record.status == OcrStatus.RUNNING:
        save_ocr(
            courses_dir=courses_dir,
            course_id=course_id,
            doc_id=doc_id,
            record=transition_ocr(record=record, status=status, error=error),
        )
