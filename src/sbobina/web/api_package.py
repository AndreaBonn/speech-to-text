import os
import re
from collections.abc import AsyncIterator
from contextlib import ExitStack
from tempfile import TemporaryFile
from typing import IO
from urllib.parse import quote

import anyio
from fastapi import APIRouter
from starlette.responses import StreamingResponse

from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import ExportOptions
from sbobina.web.course_dependencies import Course, Services

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


@router.get("")
def export_course(
    course: Course, services: Services, docs: str = ""
) -> StreamingResponse:
    """Download a course package streamed from an anonymous temporary file."""
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
