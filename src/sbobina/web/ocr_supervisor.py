"""Supervisor-side helpers for the "ocr" action.

Mirrors generation_supervisor.py's role for "generation": the queue helpers
(submit/cancel/claim) only need a JobStore, execute/launch need the
supervisor's own lock and process slot (TYPE_CHECKING-only import avoids the
circular import, since supervisor.py imports this module at runtime).
"""

import subprocess
from typing import TYPE_CHECKING

from sbobina.course_registry import find_by_key
from sbobina.document_models import DocumentKind, DocumentStatus
from sbobina.settings import settings
from sbobina.web.document_store import document_dir, read_document
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.ocr_queue import cancel_ocr_action, require_cancellable, transition_ocr
from sbobina.web.ocr_store import OcrRun, OcrStatus, create_ocr, load_ocr, save_ocr
from sbobina.web.processes import _reap, _spawn

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

OCR_COMMAND = "ocr"
CHILD_LOG_NAME = "ocr_child.log"
OCR_TIMEOUT_CODE = "OCR_TIMEOUT"


def _require_course_id(store: JobStore, course_key: str) -> str:
    course = find_by_key(courses_dir=store.courses_dir, key=course_key)
    if course is None:
        raise NotFoundError(entity="Corso", id=course_key)
    return course.id


def _require_eligible_document(store: JobStore, course_id: str, doc_id: str) -> None:
    document = read_document(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=doc_id
    )
    if document.kind is not DocumentKind.PDF or document.status is not (
        DocumentStatus.READY_NO_TEXT
    ):
        raise ConflictError(
            message="Il documento non è ammissibile per l'OCR", code="OCR_NOT_ELIGIBLE"
        )


def submit_ocr_item(
    store: JobStore, course_key: str, doc_id: str
) -> tuple[OcrRun, WorkItem]:
    course_id = _require_course_id(store=store, course_key=course_key)
    existing = load_ocr(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=doc_id
    )
    if existing is not None and existing.status in (
        OcrStatus.QUEUED,
        OcrStatus.RUNNING,
    ):
        raise ConflictError(
            message="OCR già in coda o in esecuzione", code="OCR_ALREADY_QUEUED"
        )
    _require_eligible_document(store=store, course_id=course_id, doc_id=doc_id)
    record = create_ocr(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=doc_id
    )
    item = WorkItem(job_id=doc_id, action="ocr", course_id=course_id)
    return record, item


def cancel_ocr_item(store: JobStore, course_key: str, doc_id: str) -> WorkItem:
    """The queue item of a cancellable OCR run; writes nothing yet."""
    course_id = _require_course_id(store=store, course_key=course_key)
    require_cancellable(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=doc_id
    )
    return WorkItem(job_id=doc_id, action="ocr", course_id=course_id)


def mark_ocr_interrupted(store: JobStore, item: WorkItem) -> None:
    """Called after the child is killed, so it cannot overwrite INTERRUPTED."""
    assert item.course_id is not None
    cancel_ocr_action(
        courses_dir=store.courses_dir, course_id=item.course_id, doc_id=item.job_id
    )


def claim_ocr_item(store: JobStore, item: WorkItem) -> bool:
    """True once this OCR run is marked RUNNING; False if already claimed."""
    assert item.course_id is not None
    record = load_ocr(
        courses_dir=store.courses_dir, course_id=item.course_id, doc_id=item.job_id
    )
    if record is None or record.status != OcrStatus.QUEUED:
        return False
    save_ocr(
        courses_dir=store.courses_dir,
        course_id=item.course_id,
        doc_id=item.job_id,
        record=transition_ocr(record=record, status=OcrStatus.RUNNING),
    )
    return True


def launch_ocr_process(
    supervisor: "Supervisor", item: WorkItem
) -> subprocess.Popen[bytes]:
    assert item.course_id is not None
    directory = document_dir(
        courses_dir=supervisor._store.courses_dir,
        course_id=item.course_id,
        doc_id=item.job_id,
    )
    process = _spawn(
        command=[*supervisor._options.command, OCR_COMMAND, str(directory)],
        log_path=directory / CHILD_LOG_NAME,
    )
    supervisor._process = process
    return process


def _wait_for_ocr_process(process: subprocess.Popen[bytes]) -> int | None:
    """Exit code, or None if the child is still running after the timeout."""
    try:
        return process.wait(timeout=settings.ocr_process_timeout_s)
    except subprocess.TimeoutExpired:
        return None


def _finish_timed_out_ocr(
    supervisor: "Supervisor", item: WorkItem, process: subprocess.Popen[bytes]
) -> None:
    _reap(
        process=process,
        timeout_s=supervisor._options.terminate_timeout_s,
        graceful=False,
    )
    with supervisor._condition:
        supervisor._release_process(process=process)
        supervisor._finish_failed(item=item, code=OCR_TIMEOUT_CODE)


def execute_ocr_action(
    supervisor: "Supervisor", item: WorkItem, ollama_unavailable_exit: int
) -> None:
    """The child persists its own ocr.json/text.json/document.json on success;
    a crash (non-zero exit) or a timeout (A4, security: the single queue
    worker must not block forever behind a hung or looping child) are the
    only cases the supervisor finalizes here."""
    with supervisor._condition:
        if supervisor._stopping:
            return
        process = launch_ocr_process(supervisor=supervisor, item=item)
    return_code = _wait_for_ocr_process(process=process)
    if return_code is None:
        _finish_timed_out_ocr(supervisor=supervisor, item=item, process=process)
        return
    with supervisor._condition:
        supervisor._release_process(process=process)
        if return_code != 0:
            code = (
                "OLLAMA_UNAVAILABLE"
                if return_code == ollama_unavailable_exit
                else "STAGE_FAILED"
            )
            supervisor._finish_failed(item=item, code=code)
