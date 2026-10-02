"""Upload, listing and retrieval of course documents (T015, D4)."""

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.encoders import jsonable_encoder
from starlette.responses import FileResponse, Response

from sbobina.course_registry import find_by_key, get_or_create
from sbobina.courses import course_key
from sbobina.document_models import (
    EXTRACTED_STATUSES,
    CourseDocument,
    DocumentKind,
)
from sbobina.settings import Settings
from sbobina.web.document_store import (
    document_dir,
    iter_documents,
    original_path,
    read_document,
    read_text,
)
from sbobina.web.document_upload import discard_upload, store_upload
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.extraction_worker import ExtractionWorker
from sbobina.web.upload_limit import BYTES_PER_MB

router = APIRouter(prefix="/api/v1/courses")
MEDIA_TYPES: dict[DocumentKind, str] = {
    DocumentKind.PDF: "application/pdf",
    DocumentKind.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentKind.PPTX: (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    DocumentKind.TXT: "text/plain; charset=utf-8",
    DocumentKind.MD: "text/markdown; charset=utf-8",
}


@dataclass(frozen=True)
class DocumentServices:
    settings: Settings
    courses_dir: Path
    worker: ExtractionWorker


def _services(request: Request) -> DocumentServices:
    store = request.app.state.job_store
    return DocumentServices(
        settings=request.app.state.settings,
        courses_dir=store.courses_dir,
        worker=request.app.state.extraction_worker,
    )


Services = Annotated[DocumentServices, Depends(_services)]


def _course_for_upload(key: str, services: DocumentServices) -> tuple[str, bool]:
    """Course id for the upload, and whether this request registered it."""
    normalized = course_key(label=key)
    if not normalized:
        raise ConflictError(message="Seleziona un corso", code="COURSE_REQUIRED")
    existing = find_by_key(courses_dir=services.courses_dir, key=normalized)
    if existing is not None:
        return existing.id, False
    course = get_or_create(courses_dir=services.courses_dir, key=normalized, label=key)
    return course.id, True


def _document_course_id(key: str, services: DocumentServices) -> str:
    course = find_by_key(courses_dir=services.courses_dir, key=course_key(label=key))
    if course is None:
        raise NotFoundError(entity="Documento", id=key)
    return course.id


def _find_document(key: str, doc_id: str, services: DocumentServices) -> CourseDocument:
    course_id = _document_course_id(key=key, services=services)
    return read_document(
        courses_dir=services.courses_dir, course_id=course_id, doc_id=doc_id
    )


@router.post("/{key:path}/documents", status_code=202)
async def create_document(
    key: str, services: Services, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """Accept a multipart document, sniff its kind and queue extraction."""
    course_id, is_new_course = _course_for_upload(key=key, services=services)
    doc_dir = document_dir(
        courses_dir=services.courses_dir, course_id=course_id, doc_id=str(uuid4())
    )
    await anyio.to_thread.run_sync(partial(doc_dir.mkdir, parents=True))
    try:
        document = await store_upload(
            file=file,
            doc_dir=doc_dir,
            limit=services.settings.course_doc_max_mb * BYTES_PER_MB,
            worker=services.worker,
        )
    except BaseException:
        course_dir = services.courses_dir / course_id if is_new_course else None
        await discard_upload(doc_dir=doc_dir, course_dir=course_dir)
        raise
    return {"data": jsonable_encoder(document)}


@router.get("/{key:path}/documents")
def list_documents(
    key: str,
    services: Services,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 20,
) -> dict[str, Any]:
    """Return a course's documents, newest first; an unregistered course is empty."""
    course = find_by_key(courses_dir=services.courses_dir, key=course_key(label=key))
    documents = (
        sorted(
            iter_documents(courses_dir=services.courses_dir, course_id=course.id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        if course is not None
        else []
    )
    total = len(documents)
    start = (page - 1) * per_page
    return {
        "data": [
            jsonable_encoder(item) for item in documents[start : start + per_page]
        ],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/{key:path}/documents/{doc_id}")
def get_document(key: str, doc_id: str, services: Services) -> dict[str, Any]:
    """Return one document's metadata."""
    return {
        "data": jsonable_encoder(
            _find_document(key=key, doc_id=doc_id, services=services)
        )
    }


@router.get("/{key:path}/documents/{doc_id}/file")
def download_document(key: str, doc_id: str, services: Services) -> FileResponse:
    """Serve the original upload as an attachment, named after the source file."""
    document = _find_document(key=key, doc_id=doc_id, services=services)
    doc_dir = document_dir(
        courses_dir=services.courses_dir, course_id=document.course_id, doc_id=doc_id
    )
    path = original_path(doc_dir=doc_dir, kind=document.kind)
    name = document.filename or f"{doc_id}.{document.kind.value}"
    response = FileResponse(
        path=path, media_type=MEDIA_TYPES[document.kind], filename=name
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/{key:path}/documents/{doc_id}/pages/{n}")
def get_document_page(
    key: str, doc_id: str, n: Annotated[int, PathParam(ge=1)], services: Services
) -> dict[str, Any]:
    """Return one extracted page of text; not found if out of range or not ready."""
    document = _find_document(key=key, doc_id=doc_id, services=services)
    if document.status not in EXTRACTED_STATUSES:
        raise NotFoundError(entity="Pagina", id=str(n))
    doc_dir = document_dir(
        courses_dir=services.courses_dir, course_id=document.course_id, doc_id=doc_id
    )
    stored = read_text(doc_dir=doc_dir)
    if n > len(stored.pages):
        raise NotFoundError(entity="Pagina", id=str(n))
    page = stored.pages[n - 1]
    return {
        "data": {"text": page.text, "no_text": page.no_text},
        "meta": {"page": n, "total_pages": len(stored.pages)},
    }


@router.delete("/{key:path}/documents/{doc_id}", status_code=204)
def delete_document(key: str, doc_id: str, services: Services) -> Response:
    """Remove a document and its files; reject one still being extracted."""
    document = _find_document(key=key, doc_id=doc_id, services=services)
    services.worker.remove_if_idle(course_id=document.course_id, doc_id=doc_id)
    return Response(status_code=204)
