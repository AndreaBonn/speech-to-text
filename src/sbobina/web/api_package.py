import os
import re
from collections.abc import AsyncIterator
from contextlib import ExitStack
from tempfile import TemporaryFile
from typing import IO
from urllib.parse import quote
from uuid import uuid4

import anyio
from fastapi import APIRouter
from starlette.responses import StreamingResponse

from sbobina.course_registry import CourseRecord
from sbobina.courses import course_key, effective_course
from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import ExportOptions
from sbobina.web.course_dependencies import ListedCourse, ReviewServices, Services

router = APIRouter(prefix="/api/v1/courses/{key:path}/export")
CHUNK_BYTES = 1024 * 1024


def _package_file(request: ExportRequest) -> IO[bytes]:
    """Write the package into an anonymous temporary file, rewound.

    TemporaryFile has no name on disk on POSIX and is deleted by the OS when
    closed on Windows, so a finished, aborted or failed download leaves no zip.
    """
    with ExitStack() as on_failure:
        handle = on_failure.enter_context(TemporaryFile(suffix=".sbobina.zip"))
        write_package(target=handle, request=request)
        on_failure.pop_all()  # the stream owns the file from here
    handle.seek(0)
    return handle


async def _stream(handle: IO[bytes]) -> AsyncIterator[bytes]:
    # The finally also runs when the client disconnects and Starlette closes
    # the iterator, unlike a background task that only runs after a full send.
    try:
        while chunk := await anyio.to_thread.run_sync(handle.read, CHUNK_BYTES):
            yield chunk
    finally:
        handle.close()


def content_disposition(filename: str) -> str:
    """ASCII `filename` for old clients, UTF-8 `filename*` for accented labels."""
    fallback = (
        filename.encode(encoding="ascii", errors="replace").decode().replace("?", "-")
    )
    return f"attachment; filename=\"{fallback}\"; filename*=utf-8''{quote(filename)}"


def _lecture_label(key: str, services: ReviewServices) -> str:
    """The course name as the newest lecture spells it, as the course list does."""
    store = services.store
    newest_first = sorted(
        store.iter_records(), key=lambda record: record.created_at, reverse=True
    )
    for record in newest_first:
        label = effective_course(
            course=store.read_meta(job_id=str(record.id)).course,
            subject=record.config.subject,
        )
        if label and course_key(label=label) == key:
            return label
    return key


def _lecture_only_course(key: str, services: ReviewServices) -> CourseRecord:
    """A stand-in record for a course that has lectures but no registry entry.

    F49: it has no documents, generations or cards, so the package only needs
    its key (which lectures) and label; nothing is written to the registry.
    """
    normalized = course_key(label=key)
    return CourseRecord(
        id=str(uuid4()),
        key=normalized,
        label=_lecture_label(key=normalized, services=services),
        created_at=services.now,
        updated_at=services.now,
    )


@router.get("")
def export_course(
    key: str, listed: ListedCourse, services: Services, docs: str = ""
) -> StreamingResponse:
    """Download a course package streamed from an anonymous temporary file."""
    course = listed or _lecture_only_course(key=key, services=services)
    # docs is a comma-separated set of excluded document IDs; empty includes all.
    options = ExportOptions(
        excluded_document_ids=frozenset(
            part.strip() for part in docs.split(",") if part.strip()
        )
    )
    handle = _package_file(
        request=ExportRequest(
            course=course,
            store=services.store,
            options=options,
            now=services.now,
        )
    )
    name = (
        re.sub(pattern=r"[^\w.-]+", repl="-", string=course.label).strip(".-")
        or "course"
    )
    filename = f"{name}-{services.now.date().isoformat()}.sbobina.zip"
    return StreamingResponse(
        content=_stream(handle=handle),
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(filename=filename),
            "Content-Length": str(os.fstat(handle.fileno()).st_size),
            "X-Content-Type-Options": "nosniff",
        },
    )
