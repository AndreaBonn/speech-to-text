import threading
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, Field

from sbobina.book import book_paragraphs, render_book_text
from sbobina.docx_export import render_book_docx
from sbobina.manual_edit import EditConflictError, InvalidSpanError, replace_span
from sbobina.models import Transcript, load_transcript, transcript_to_json
from sbobina.pipeline import write_markdown
from sbobina.settings import Settings
from sbobina.web.api_files import (
    TRANSCRIPT_FILES,
    TranscriptVariant,
    download_name,
    existing_file,
    find_job,
    job_render_options,
    reader_payload,
    transcript_revision,
)
from sbobina.web.errors import ConflictError, ValidationError
from sbobina.web.job_models import JobRecord, JobStatus
from sbobina.web.job_store import atomic_write

router = APIRouter(prefix="/api/v1/jobs")

ExportFormat = Literal["docx", "txt"]
EXPORT_MEDIA_TYPES: dict[str, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
}
EXPORT_STEMS = {"original": "audio", "corrected": "audio.corretto"}
CORRECTED = TRANSCRIPT_FILES["corrected"]
ORIGINAL = TRANSCRIPT_FILES["original"]
BUSY_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)
MAX_EDIT_CHARS = 2000
MAX_EXPECTED_CHARS = 20000
# Edits are read-modify-write on one JSON file; the threadpool would
# otherwise let two saves interleave and drop one of them.
_EDIT_LOCK = threading.Lock()


class JobInProgressError(ConflictError):
    def __init__(self) -> None:
        super().__init__(
            message="La trascrizione è ancora in lavorazione, riprova a job finito",
            code="JOB_IN_PROGRESS",
        )


class SpanEdit(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    expected: str = Field(max_length=MAX_EXPECTED_CHARS)
    text: str = Field(max_length=MAX_EDIT_CHARS)
    revision: str = Field(min_length=1, max_length=64)


def _document_title(record: JobRecord) -> str:
    if record.config.subject:
        return record.config.subject
    if record.source_name:
        return Path(record.source_name).stem
    return f"Lezione del {record.created_at.strftime('%d/%m/%Y')}"


def _attachment(filename: str) -> str:
    # Same RFC 5987 form Starlette's FileResponse sends for non-ASCII names.
    quoted = quote(filename)
    if quoted == filename:
        return f'attachment; filename="{filename}"'
    return f"attachment; filename*=utf-8''{quoted}"


def _save_corrected(
    request: Request, record: JobRecord, path: Path, transcript: Transcript
) -> None:
    atomic_write(path=path, content=transcript_to_json(transcript))
    settings: Settings = request.app.state.settings
    config = Settings.model_validate(
        {**settings.model_dump(), **record.config.model_dump()}
    )
    write_markdown(transcript, json_path=path, config=config)


def _require_revision(path: Path, revision: str) -> None:
    if transcript_revision(path.read_text(encoding="utf-8")) != revision:
        raise ConflictError(
            message="Il testo è stato modificato altrove", code="EDIT_CONFLICT"
        )


def _editable_job(request: Request, job_id: str) -> tuple[JobRecord, Path]:
    record, directory = find_job(request=request, job_id=job_id)
    if record.status in BUSY_STATUSES:
        raise JobInProgressError()
    return record, directory


@router.get("/{job_id}/export/{fmt}")
def export_transcript(
    request: Request,
    job_id: str,
    fmt: ExportFormat,
    variant: Annotated[TranscriptVariant, Query()] = "corrected",
) -> Response:
    """Download the transcript as a book-style document, without timestamps."""
    record, directory = find_job(request=request, job_id=job_id)
    path = existing_file(directory=directory, name=TRANSCRIPT_FILES[variant])
    paragraphs = book_paragraphs(
        transcript=load_transcript(path),
        options=job_render_options(request=request, record=record),
    )
    title = _document_title(record)
    content: bytes | str = (
        render_book_docx(title=title, paragraphs=paragraphs)
        if fmt == "docx"
        else render_book_text(title=title, paragraphs=paragraphs)
    )
    name = download_name(
        source_name=record.source_name, name=f"{EXPORT_STEMS[variant]}.{fmt}"
    )
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": _attachment(filename=name)},
    )


@router.post("/{job_id}/transcript/corrected")
def create_corrected(
    request: Request, job_id: str, response: Response
) -> dict[str, Any]:
    """Start a hand-corrected copy from the original when no correction exists."""
    record, directory = _editable_job(request=request, job_id=job_id)
    with _EDIT_LOCK:
        target = directory / CORRECTED
        if target.is_file():
            return {"data": {"created": False}, "meta": {}}
        original = load_transcript(existing_file(directory=directory, name=ORIGINAL))
        _save_corrected(
            request=request, record=record, path=target, transcript=original
        )
    response.status_code = status.HTTP_201_CREATED
    return {"data": {"created": True}, "meta": {}}


@router.patch("/{job_id}/transcript/corrected")
def edit_corrected(request: Request, job_id: str, edit: SpanEdit) -> dict[str, Any]:
    """Replace a span of the corrected transcript; JSON and Markdown are rewritten.

    The reply is the reader payload of the saved text, so the page re-renders
    from what is on disk rather than from its own guess.
    """
    record, directory = _editable_job(request=request, job_id=job_id)
    with _EDIT_LOCK:
        path = existing_file(directory=directory, name=CORRECTED)
        _require_revision(path=path, revision=edit.revision)
        try:
            edited = replace_span(
                transcript=load_transcript(path),
                start=edit.start,
                end=edit.end,
                text=edit.text,
                expected=edit.expected,
            )
        except InvalidSpanError as err:
            raise ValidationError(message=str(err)) from err
        except EditConflictError as err:
            raise ConflictError(message=str(err), code="EDIT_CONFLICT") from err
        _save_corrected(request=request, record=record, path=path, transcript=edited)
    return reader_payload(
        transcript=edited,
        options=job_render_options(request=request, record=record),
        revision=transcript_revision(transcript_to_json(edited)),
    )
