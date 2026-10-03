"""Start, follow and cancel OCR of a scanned course document (T052).

The run itself is a supervisor queue action (ocr_supervisor.py); these
routes only submit, read ocr.json and cancel.
"""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from sbobina.course_registry import find_by_key
from sbobina.courses import course_key
from sbobina.web.errors import NotFoundError
from sbobina.web.ocr_store import OcrRun, load_ocr
from sbobina.web.supervisor import Supervisor

router = APIRouter(prefix="/api/v1/courses")


def _payload(run: OcrRun) -> dict[str, Any]:
    return {"data": asdict(run) | {"status": run.status.value}}


def _supervisor(request: Request) -> Supervisor:
    supervisor: Supervisor = request.app.state.supervisor
    return supervisor


@router.post("/{key:path}/documents/{doc_id}/ocr", status_code=202)
def start_ocr(key: str, doc_id: str, request: Request) -> dict[str, Any]:
    run = _supervisor(request=request).submit_ocr(
        course_key=course_key(label=key), doc_id=doc_id
    )
    return _payload(run=run)


@router.get("/{key:path}/documents/{doc_id}/ocr")
def get_ocr(key: str, doc_id: str, request: Request) -> dict[str, Any]:
    courses_dir = request.app.state.job_store.courses_dir
    course = find_by_key(courses_dir=courses_dir, key=course_key(label=key))
    run = (
        None
        if course is None
        else load_ocr(courses_dir=courses_dir, course_id=course.id, doc_id=doc_id)
    )
    if run is None:
        raise NotFoundError(entity="OCR", id=doc_id)
    return _payload(run=run)


@router.post("/{key:path}/documents/{doc_id}/ocr/cancel")
def cancel_ocr(key: str, doc_id: str, request: Request) -> dict[str, Any]:
    _supervisor(request=request).cancel_ocr(
        course_key=course_key(label=key), doc_id=doc_id
    )
    return get_ocr(key=key, doc_id=doc_id, request=request)
