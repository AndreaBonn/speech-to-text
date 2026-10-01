from dataclasses import asdict
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError

from sbobina.models import load_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES, TranscriptVariant
from sbobina.web.errors import NotFoundError
from sbobina.web.job_store import JobStore
from sbobina.wer import compute_wer

router = APIRouter(prefix="/api/v1/wer")
# A transcript of a whole lecture is a few hundred KB of text.
MAX_TEXT_BYTES = 5 * 1024 * 1024
# Reference + hypothesis + form overhead, checked before Starlette spools the body.
WER_REQUEST_LIMIT_BYTES = 2 * MAX_TEXT_BYTES + 1024 * 1024


def _field_error(field: str, message: str) -> RequestValidationError:
    return RequestValidationError(
        errors=[{"type": "value_error", "loc": (field,), "msg": message}]
    )


async def _read_text(file: UploadFile, field: str) -> str:
    raw = await file.read(MAX_TEXT_BYTES + 1)
    if len(raw) > MAX_TEXT_BYTES:
        raise _field_error(field=field, message="File di testo troppo grande")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _field_error(
            field=field, message="Il file deve essere testo UTF-8 (.txt)"
        ) from error


def _job_text(request: Request, job_id: str, variant: str) -> str:
    store: JobStore = request.app.state.job_store
    record = store.get(job_id=job_id)
    path = store.jobs_dir / str(record.id) / TRANSCRIPT_FILES[variant]
    if not path.is_file():
        raise NotFoundError(entity="Trascrizione", id=TRANSCRIPT_FILES[variant])
    return load_transcript(path).text


@router.post("")
async def compare(
    request: Request,
    reference: Annotated[UploadFile, File()],
    hypothesis: Annotated[UploadFile | None, File()] = None,
    job_id: Annotated[str | None, Form()] = None,
    variant: Annotated[TranscriptVariant, Form()] = "original",
) -> dict[str, Any]:
    """Word error rate of a job transcript (or a .txt) against a reference .txt."""
    reference_text = await _read_text(file=reference, field="reference")
    if hypothesis is not None:
        hypothesis_text = await _read_text(file=hypothesis, field="hypothesis")
    elif job_id:
        hypothesis_text = await anyio.to_thread.run_sync(
            lambda: _job_text(request=request, job_id=job_id, variant=variant)
        )
    else:
        raise _field_error(
            field="hypothesis", message="Scegli una lezione o carica un testo"
        )
    try:
        report = compute_wer(reference=reference_text, hypothesis=hypothesis_text)
    except ValueError as error:
        raise _field_error(field="reference", message=str(error)) from error
    return {"data": asdict(report), "meta": {}}
