"""CRUD and exports for course generations (T034, D3/D5)."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import Response

from sbobina.course_registry import find_by_key
from sbobina.courses import course_key
from sbobina.docx_export import (
    render_exam_docx,
    render_solutions_docx,
    render_summary_docx,
)
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.generation_render import (
    render_exam_markdown,
    render_solutions_markdown,
    render_summary_markdown,
)
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.generation_citations_api import (
    CitationContext,
    doc_filenames,
    generation_detail_payload,
)
from sbobina.web.generation_store import (
    generation_dir,
    generation_path,
    load_generation,
)
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor

router = APIRouter(prefix="/api/v1/courses")
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_EXAM_FORMATS = frozenset(
    {GenerationFormat.MULTIPLE_CHOICE, GenerationFormat.OPEN, GenerationFormat.ORAL}
)
_SUMMARY_FORMATS = frozenset({GenerationFormat.SUMMARY})


@dataclass(frozen=True)
class GenerationServices:
    store: JobStore
    supervisor: Supervisor

    @property
    def courses_dir(self) -> Path:
        return self.store.courses_dir


def _services(request: Request) -> GenerationServices:
    return GenerationServices(
        store=request.app.state.job_store, supervisor=request.app.state.supervisor
    )


Services = Annotated[GenerationServices, Depends(_services)]


def _normalized_key(key: str) -> str:
    normalized = course_key(label=key)
    if not normalized:
        raise ConflictError(message="Seleziona un corso", code="COURSE_REQUIRED")
    return normalized


def _course_id_for_key(key: str, services: GenerationServices) -> str:
    course = find_by_key(courses_dir=services.courses_dir, key=course_key(label=key))
    if course is None:
        raise NotFoundError(entity="Corso", id=key)
    return course.id


def _list_records(courses_dir: Path, course_id: str) -> list[GenerationRecord]:
    """Every generation of a course, newest file first (no created_at field
    on GenerationRecord: mtime is the same ordering key the queue uses)."""
    directory = generation_dir(courses_dir=courses_dir, course_id=course_id)
    if not directory.is_dir():
        return []
    paths = sorted(
        directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    return [
        load_generation(courses_dir=courses_dir, course_id=course_id, gen_id=path.stem)
        for path in paths
    ]


@router.post("/{key:path}/generations", status_code=202)
def create_generation(
    key: str, body: GenerationRequest, services: Services
) -> dict[str, Any]:
    """Queue a generation; an unregistered course is rejected, not created
    (unlike document upload: a generation needs material to already exist)."""
    normalized = _normalized_key(key=key)
    record = services.supervisor.submit_generation(course_key=normalized, request=body)
    return {"data": jsonable_encoder(record)}


@router.get("/{key:path}/generations")
def list_generations(
    key: str,
    services: Services,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 20,
) -> dict[str, Any]:
    """An unregistered course has no generations: empty page, not 404."""
    course = find_by_key(courses_dir=services.courses_dir, key=course_key(label=key))
    records = (
        _list_records(courses_dir=services.courses_dir, course_id=course.id)
        if course is not None
        else []
    )
    total = len(records)
    start = (page - 1) * per_page
    return {
        "data": [
            jsonable_encoder(record) for record in records[start : start + per_page]
        ],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/{key:path}/generations/{gen_id}")
def get_generation(key: str, gen_id: str, services: Services) -> dict[str, Any]:
    """Detail with citations resolved; also serves as the polling endpoint."""
    course_id = _course_id_for_key(key=key, services=services)
    record = load_generation(
        courses_dir=services.courses_dir, course_id=course_id, gen_id=gen_id
    )
    context = CitationContext(
        courses_dir=services.courses_dir,
        store=services.store,
        course_id=course_id,
        key=key,
    )
    return {"data": generation_detail_payload(record=record, context=context)}


@router.delete("/{key:path}/generations/{gen_id}", status_code=204)
def delete_generation(key: str, gen_id: str, services: Services) -> Response:
    course_id = _course_id_for_key(key=key, services=services)
    record = load_generation(
        courses_dir=services.courses_dir, course_id=course_id, gen_id=gen_id
    )
    if record.status in (GenerationStatus.QUEUED, GenerationStatus.RUNNING):
        raise ConflictError(message="Generazione in corso", code="GENERATION_BUSY")
    generation_path(
        courses_dir=services.courses_dir, course_id=course_id, gen_id=gen_id
    ).unlink(missing_ok=True)
    return Response(status_code=204)


@router.post("/{key:path}/generations/{gen_id}/cancel")
def cancel_generation(key: str, gen_id: str, services: Services) -> dict[str, Any]:
    normalized = _normalized_key(key=key)
    services.supervisor.cancel_generation(course_key=normalized, gen_id=gen_id)
    course_id = _course_id_for_key(key=key, services=services)
    record = load_generation(
        courses_dir=services.courses_dir, course_id=course_id, gen_id=gen_id
    )
    return {"data": jsonable_encoder(record)}


@dataclass(frozen=True)
class GenerationFile:
    formats: frozenset[GenerationFormat]
    media_type: str
    render: Callable[[GenerationRecord, dict[str, str]], bytes]


def _compito_md(record: GenerationRecord, _names: dict[str, str]) -> bytes:
    return render_exam_markdown(questions=record.questions).encode("utf-8")


def _soluzioni_md(record: GenerationRecord, names: dict[str, str]) -> bytes:
    rendered = render_solutions_markdown(
        questions=record.questions, doc_filenames=names
    )
    return rendered.encode("utf-8")


def _riassunto_md(record: GenerationRecord, names: dict[str, str]) -> bytes:
    rendered = render_summary_markdown(sections=record.sections, doc_filenames=names)
    return rendered.encode("utf-8")


def _compito_docx(record: GenerationRecord, _names: dict[str, str]) -> bytes:
    return render_exam_docx(generation=record)


def _soluzioni_docx(record: GenerationRecord, names: dict[str, str]) -> bytes:
    return render_solutions_docx(generation=record, doc_filenames=names)


def _riassunto_docx(record: GenerationRecord, names: dict[str, str]) -> bytes:
    return render_summary_docx(generation=record, doc_filenames=names)


GENERATION_FILES: dict[str, GenerationFile] = {
    "compito.md": GenerationFile(
        formats=_EXAM_FORMATS, media_type=MARKDOWN_MEDIA_TYPE, render=_compito_md
    ),
    "soluzioni.md": GenerationFile(
        formats=_EXAM_FORMATS, media_type=MARKDOWN_MEDIA_TYPE, render=_soluzioni_md
    ),
    "riassunto.md": GenerationFile(
        formats=_SUMMARY_FORMATS, media_type=MARKDOWN_MEDIA_TYPE, render=_riassunto_md
    ),
    "compito.docx": GenerationFile(
        formats=_EXAM_FORMATS, media_type=DOCX_MEDIA_TYPE, render=_compito_docx
    ),
    "soluzioni.docx": GenerationFile(
        formats=_EXAM_FORMATS, media_type=DOCX_MEDIA_TYPE, render=_soluzioni_docx
    ),
    "riassunto.docx": GenerationFile(
        formats=_SUMMARY_FORMATS, media_type=DOCX_MEDIA_TYPE, render=_riassunto_docx
    ),
}


@router.get("/{key:path}/generations/{gen_id}/files/{name}")
def download_generation_file(
    key: str, gen_id: str, name: str, services: Services
) -> Response:
    """Export one rendered file; 404 for an unknown name, a format mismatch
    (riassunto on an exam, compito on a summary), or a generation not yet
    done (nothing to export)."""
    course_id = _course_id_for_key(key=key, services=services)
    record = load_generation(
        courses_dir=services.courses_dir, course_id=course_id, gen_id=gen_id
    )
    spec = GENERATION_FILES.get(name)
    if (
        spec is None
        or record.format not in spec.formats
        or record.status != GenerationStatus.DONE
    ):
        raise NotFoundError(entity="File", id=name)
    names = doc_filenames(
        courses_dir=services.courses_dir, course_id=course_id, record=record
    )
    response = Response(content=spec.render(record, names), media_type=spec.media_type)
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
