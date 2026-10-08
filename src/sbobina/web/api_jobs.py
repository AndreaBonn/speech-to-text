import unicodedata
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any

import anyio
import av
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError
from starlette.responses import Response

from sbobina.courses import effective_course
from sbobina.settings import Settings
from sbobina.web.errors import AppError, ConflictError
from sbobina.web.job_models import JobConfig, JobRecord, JobStatus, StudyStatus
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor
from sbobina.web.upload_limit import BYTES_PER_MB

router = APIRouter(prefix="/api/v1/jobs")
CHUNK_SIZE = 1024 * 1024
MAX_SOURCE_NAME = 200
ALLOWED_EXTENSIONS = frozenset(
    {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".webm", ".aac"}
)


@dataclass(frozen=True)
class JobServices:
    settings: Settings
    store: JobStore
    supervisor: Supervisor


def _services(request: Request) -> JobServices:
    return JobServices(
        settings=request.app.state.settings,
        store=request.app.state.job_store,
        supervisor=request.app.state.supervisor,
    )


Services = Annotated[JobServices, Depends(_services)]


async def _config(request: Request, services: Services) -> JobConfig:
    form = await request.form()
    values = services.settings.model_dump(include=set(JobConfig.model_fields))
    values.update({name: form[name] for name in JobConfig.model_fields if name in form})
    try:
        return JobConfig.model_validate(obj=values)
    except PydanticValidationError as error:
        details = [
            {**detail, "loc": ("body", *detail["loc"])} for detail in error.errors()
        ]
        raise RequestValidationError(errors=details) from error


def _invalid_file(message: str) -> RequestValidationError:
    return RequestValidationError(
        errors=[{"type": "value_error", "loc": ("file",), "msg": message}]
    )


def _check_limit(size: int, limit: int) -> None:
    if size > limit:
        raise HTTPException(
            status_code=413, detail="Il file supera il limite consentito"
        )


def _validate_audio(path: Path) -> None:
    try:
        with av.open(file=str(path)) as container:
            if not container.streams.audio:
                raise _invalid_file(message="Il file non contiene una traccia audio")
    except av.FFmpegError as error:
        raise _invalid_file(
            message="Il contenuto del file audio non è valido"
        ) from error


async def _write_upload(file: UploadFile, path: Path, limit: int) -> None:
    size = 0
    async with await anyio.open_file(file=path, mode="wb") as output:
        while chunk := await file.read(size=CHUNK_SIZE):
            size += len(chunk)
            _check_limit(size=size, limit=limit)
            await output.write(chunk)
    await anyio.to_thread.run_sync(partial(_validate_audio, path=path))


def source_name(filename: str) -> str:
    """Keep only the file's own name (POSIX or Windows path), at most 200 chars."""
    name = PureWindowsPath(PurePosixPath(filename).name).name
    # Drop control and format characters (newlines, NUL, bidi overrides such as
    # U+202E) so the name cannot reorder or break the line it is shown in.
    name = "".join(
        char for char in name if not unicodedata.category(char).startswith("C")
    ).strip()
    if len(name) <= MAX_SOURCE_NAME:
        return name
    suffix = Path(name).suffix
    return name[: MAX_SOURCE_NAME - len(suffix)] + suffix


async def _save_upload(
    file: UploadFile, config: JobConfig, services: JobServices, extension: str
) -> JobRecord:
    record = await anyio.to_thread.run_sync(
        partial(
            services.store.create,
            config=config,
            source_name=source_name(filename=file.filename or ""),
        )
    )
    directory = services.store.jobs_dir / str(record.id)
    path = directory / f"audio{extension}.part"
    submitted = False
    try:
        await _write_upload(
            file=file,
            path=path,
            limit=services.settings.web_max_upload_mb * BYTES_PER_MB,
        )
        await anyio.to_thread.run_sync(
            partial(path.rename, target=directory / f"audio{extension}")
        )
        await anyio.to_thread.run_sync(
            partial(services.supervisor.submit, job_id=str(record.id))
        )
        submitted = True
        return record
    except OSError as error:
        raise AppError(message="Unable to save uploaded audio") from error
    finally:
        if not submitted:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(
                    partial(services.store.delete, job_id=str(record.id))
                )


@router.post("", status_code=201)
async def create_job(
    request: Request,
    services: Services,
    config: Annotated[JobConfig, Depends(_config)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Validate and persist multipart audio before submitting a queued job."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise _invalid_file(message="Estensione del file audio non consentita")
    record = await _save_upload(
        file=file, config=config, services=services, extension=extension
    )
    return {"data": _job_dict(record=record, store=services.store)}


def _job_dict(record: JobRecord, store: JobStore) -> dict[str, Any]:
    """Job data plus the effective course (N4): meta.json's course, or subject."""
    data = record.model_dump(mode="json")
    meta = store.read_meta(job_id=str(record.id))
    data["course"] = effective_course(course=meta.course, subject=record.config.subject)
    return data


@router.get("")
def list_jobs(
    services: Services,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 20,
    course: str | None = None,
) -> dict[str, Any]:
    """Return jobs ordered by creation time with pagination metadata."""
    result = services.store.list(page=page, per_page=per_page, course_key=course)
    return {
        "data": [
            _job_dict(record=record, store=services.store) for record in result.items
        ],
        "meta": {
            "page": result.page,
            "per_page": result.per_page,
            "total": result.total,
            "total_pages": result.total_pages,
        },
    }


@router.get("/{job_id}")
def get_job(job_id: str, services: Services) -> dict[str, Any]:
    """Return one job or raise NotFoundError."""
    record = services.store.get(job_id=job_id)
    return {"data": _job_dict(record=record, store=services.store)}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, services: Services) -> dict[str, Any]:
    """Cancel a queued or running job; reject terminal jobs with HTTP 409."""
    services.supervisor.cancel(job_id=job_id)
    return get_job(job_id=job_id, services=services)


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, services: Services) -> Response:
    """Remove a terminal job and its files; reject active jobs with HTTP 409."""
    record = services.store.get(job_id=job_id)
    # A study keeps the job DONE while its child writes into the job directory.
    study_active = record.study is not None and record.study.status in (
        StudyStatus.QUEUED,
        StudyStatus.RUNNING,
    )
    if record.status in (JobStatus.RUNNING, JobStatus.QUEUED) or study_active:
        raise ConflictError(
            message="Annulla il job prima di eliminarlo", code="JOB_NOT_DELETABLE"
        )
    services.store.delete(job_id=job_id)
    return Response(status_code=204)
