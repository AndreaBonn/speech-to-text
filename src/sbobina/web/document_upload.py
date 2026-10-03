"""Receiving a course document upload: stream, sniff, queue, or clean up."""

import hashlib
import shutil
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import anyio
from fastapi import HTTPException, UploadFile

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.document_sniff import ArchiveTooLargeError, sniff_document
from sbobina.web.api_jobs import source_name
from sbobina.web.document_store import original_path
from sbobina.web.extraction_worker import ExtractionWorker

CHUNK_SIZE = 1024 * 1024
HEAD_SNIFF_BYTES = 32
TEMP_UPLOAD_NAME = "upload.part"


async def _write_upload(file: UploadFile, path: Path, limit: int) -> tuple[int, str]:
    """Stream the upload to disk, hashing it, enforcing the byte limit."""
    size = 0
    digest = hashlib.sha256()
    async with await anyio.open_file(file=path, mode="wb") as output:
        while chunk := await file.read(size=CHUNK_SIZE):
            size += len(chunk)
            if size > limit:
                raise HTTPException(
                    status_code=413, detail="Il file supera il limite consentito"
                )
            digest.update(chunk)
            await output.write(chunk)
    return size, digest.hexdigest()


def _sniff_kind(path: Path, filename: str) -> DocumentKind:
    with path.open("rb") as source:
        head = source.read(HEAD_SNIFF_BYTES)
    try:
        # Sniffing an Office file checks the archive limits before opening it.
        kind = sniff_document(head=head, path=path, filename=filename)
    except ArchiveTooLargeError as error:
        raise HTTPException(
            status_code=413, detail="Il documento supera i limiti consentiti"
        ) from error
    if kind is None:
        raise HTTPException(
            status_code=415, detail="Formato del documento non supportato"
        )
    return kind


async def _accept_upload(
    file: UploadFile, doc_dir: Path, limit: int
) -> tuple[DocumentKind, int, str]:
    temp_path = doc_dir / TEMP_UPLOAD_NAME
    size, digest = await _write_upload(file=file, path=temp_path, limit=limit)
    kind = await anyio.to_thread.run_sync(
        partial(_sniff_kind, path=temp_path, filename=file.filename or "")
    )
    final_path = original_path(doc_dir=doc_dir, kind=kind)
    await anyio.to_thread.run_sync(partial(temp_path.rename, target=final_path))
    return kind, size, digest


async def store_upload(
    file: UploadFile, doc_dir: Path, limit: int, worker: ExtractionWorker
) -> CourseDocument:
    """Stream, hash and sniff an upload, then queue it for extraction."""
    kind, size, digest = await _accept_upload(file=file, doc_dir=doc_dir, limit=limit)
    document = CourseDocument(
        id=doc_dir.name,
        course_id=doc_dir.parent.parent.name,
        filename=source_name(filename=file.filename or ""),
        kind=kind,
        size=size,
        sha256=digest,
        status=DocumentStatus.UPLOADING,
        error=None,
        pages=None,
        created_at=datetime.now(tz=UTC),
    )
    return await anyio.to_thread.run_sync(
        partial(worker.enqueue_new, document=document)
    )


def _remove_upload(doc_dir: Path, course_dir: Path | None) -> None:
    shutil.rmtree(doc_dir, ignore_errors=True)
    if course_dir is None:
        return
    try:
        # rmdir refuses a non-empty directory: a concurrent upload to the same
        # new course keeps the course alive.
        (course_dir / "documents").rmdir()
    except OSError:
        return
    shutil.rmtree(course_dir, ignore_errors=True)


async def discard_upload(doc_dir: Path, course_dir: Path | None) -> None:
    # A failed upload leaves nothing behind, not even a course it registered.
    with anyio.CancelScope(shield=True):
        await anyio.to_thread.run_sync(
            partial(_remove_upload, doc_dir=doc_dir, course_dir=course_dir)
        )
