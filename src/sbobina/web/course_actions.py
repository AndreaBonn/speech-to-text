"""Dispatch tables for the course-scoped actions ("generation", "ocr").

Both own their own record file and finalize success themselves; only
claim/execute/crash-handling go through the supervisor's single queue and
process slot, same as pipeline/study. Factored out of supervisor.py to stay
under the file size limit.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sbobina.generation_models import (
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.web.generation_queue import finish_generation
from sbobina.web.generation_supervisor import (
    cancel_generation_item,
    claim_generation_item,
    execute_generation_action,
    mark_generation_interrupted,
    submit_generation_item,
)
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.ocr_queue import finish_ocr
from sbobina.web.ocr_store import OcrRun, OcrStatus
from sbobina.web.ocr_supervisor import (
    cancel_ocr_item,
    claim_ocr_item,
    execute_ocr_action,
    mark_ocr_interrupted,
    submit_ocr_item,
)

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

ClaimFn = Callable[[JobStore, WorkItem], bool]
ExecuteFn = Callable[..., None]
FinishFailedFn = Callable[[Path, str, str, str], None]

CLAIM_ACTIONS: dict[str, ClaimFn] = {
    "generation": claim_generation_item,
    "ocr": claim_ocr_item,
}
EXECUTE_ACTIONS: dict[str, ExecuteFn] = {
    "generation": execute_generation_action,
    "ocr": execute_ocr_action,
}
FINISH_FAILED_ACTIONS: dict[str, FinishFailedFn] = {
    "generation": lambda courses_dir, course_id, job_id, code: finish_generation(
        courses_dir=courses_dir,
        course_id=course_id,
        gen_id=job_id,
        status=GenerationStatus.FAILED,
        error=code,
    ),
    "ocr": lambda courses_dir, course_id, job_id, code: finish_ocr(
        courses_dir=courses_dir,
        course_id=course_id,
        doc_id=job_id,
        status=OcrStatus.FAILED,
        error=code,
    ),
}


def _dequeue_and_stop_active(supervisor: "Supervisor", item: WorkItem) -> None:
    """Shared tail of cancel_generation/cancel_ocr: neither holds the GPU."""
    if item in supervisor._queue:
        supervisor._queue.remove(item)
    if supervisor._active == item:
        supervisor._stop_process(graceful=False)


def submit_generation(
    supervisor: "Supervisor", course_key: str, request: GenerationRequest
) -> GenerationRecord:
    with supervisor._condition:
        record, item = submit_generation_item(
            store=supervisor._store, course_key=course_key, request=request
        )
        supervisor._queue.append(item)
        supervisor._condition.notify()
        return record


def submit_ocr(supervisor: "Supervisor", course_key: str, doc_id: str) -> OcrRun:
    with supervisor._condition:
        record, item = submit_ocr_item(
            store=supervisor._store, course_key=course_key, doc_id=doc_id
        )
        supervisor._queue.append(item)
        supervisor._condition.notify()
        return record


def cancel_generation(supervisor: "Supervisor", course_key: str, gen_id: str) -> None:
    with supervisor._condition:
        item = cancel_generation_item(
            store=supervisor._store, course_key=course_key, gen_id=gen_id
        )
        _dequeue_and_stop_active(supervisor=supervisor, item=item)
        mark_generation_interrupted(store=supervisor._store, item=item)


def cancel_ocr(supervisor: "Supervisor", course_key: str, doc_id: str) -> None:
    with supervisor._condition:
        item = cancel_ocr_item(
            store=supervisor._store, course_key=course_key, doc_id=doc_id
        )
        _dequeue_and_stop_active(supervisor=supervisor, item=item)
        mark_ocr_interrupted(store=supervisor._store, item=item)


__all__ = [
    "CLAIM_ACTIONS",
    "EXECUTE_ACTIONS",
    "FINISH_FAILED_ACTIONS",
    "cancel_generation",
    "cancel_ocr",
    "submit_generation",
    "submit_ocr",
]
