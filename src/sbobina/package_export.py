import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import IO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sbobina.course_registry import CourseRecord
from sbobina.courses import course_key, effective_course
from sbobina.package_models import (
    ExportOptions,
    InventoryEntry,
    Manifest,
    PackageCourse,
    PackageKind,
    project_job,
)
from sbobina.web.card_store import cards_path
from sbobina.web.document_store import (
    DOCUMENT_FILENAME,
    TEXT_FILENAME,
    document_dir,
    iter_documents,
    original_path,
)
from sbobina.web.generation_store import generation_dir
from sbobina.web.job_models import JobRecord
from sbobina.web.job_store import JobStore

OPTIONAL_LECTURE_FILES: tuple[tuple[str, str, PackageKind], ...] = (
    ("audio.corretto.json", "corrected.json", "corrected"),
    ("audio.studio.json", "study.json", "study"),
)


@dataclass(frozen=True, kw_only=True)
class ExportRequest:
    store: JobStore
    course: CourseRecord
    options: ExportOptions
    now: datetime


@dataclass(frozen=True, kw_only=True)
class PackageMember:
    entry: InventoryEntry
    data: bytes


def _make_member(path: str, data: bytes, kind: PackageKind) -> PackageMember:
    entry = InventoryEntry(
        path=path, sha256=sha256(data).hexdigest(), size=len(data), kind=kind
    )
    return PackageMember(entry=entry, data=data)


def _course_jobs(request: ExportRequest) -> Iterator[JobRecord]:
    for record in request.store.iter_records():
        meta = request.store.read_meta(job_id=str(record.id))
        label = effective_course(course=meta.course, subject=record.config.subject)
        if course_key(label=label) == request.course.key:
            yield record


def _lecture_members(request: ExportRequest) -> Iterator[PackageMember]:
    for index, record in enumerate(_course_jobs(request=request)):
        directory = request.store.jobs_dir / str(record.id)
        prefix = f"lectures/{index}"
        yield _make_member(
            path=f"{prefix}/transcript.json",
            kind="transcript",
            data=(directory / "audio.json").read_bytes(),
        )
        yield _make_member(
            path=f"{prefix}/meta.json",
            kind="meta",
            data=json.dumps(
                obj=project_job(record=record), ensure_ascii=False
            ).encode(),
        )
        for source, target, kind in OPTIONAL_LECTURE_FILES:
            path = directory / source
            if path.exists():
                yield _make_member(
                    path=f"{prefix}/{target}", data=path.read_bytes(), kind=kind
                )


def _document_members(request: ExportRequest) -> Iterator[PackageMember]:
    documents = iter_documents(
        courses_dir=request.store.courses_dir, course_id=request.course.id
    )
    for index, document in enumerate(documents):
        directory = document_dir(
            courses_dir=request.store.courses_dir,
            course_id=request.course.id,
            doc_id=document.id,
        )
        prefix = f"documents/{index}"
        yield _make_member(
            path=f"{prefix}/{DOCUMENT_FILENAME}",
            kind="document",
            data=(directory / DOCUMENT_FILENAME).read_bytes(),
        )
        if document.id in request.options.excluded_document_ids:
            continue
        text = directory / TEXT_FILENAME
        if text.exists():
            yield _make_member(
                path=f"{prefix}/{TEXT_FILENAME}", data=text.read_bytes(), kind="text"
            )
        original = original_path(doc_dir=directory, kind=document.kind)
        yield _make_member(
            path=f"{prefix}/{original.name}",
            data=original.read_bytes(),
            kind="original",
        )


def iter_package_members(request: ExportRequest) -> Iterator[PackageMember]:
    """Yield allowed course content, hashing exactly the bytes to be archived."""
    yield from _lecture_members(request=request)
    yield from _document_members(request=request)
    directory = generation_dir(
        courses_dir=request.store.courses_dir, course_id=request.course.id
    )
    for index, path in enumerate(sorted(directory.glob("*.json"))):
        yield _make_member(
            path=f"generations/{index}.json", data=path.read_bytes(), kind="generation"
        )
    cards = cards_path(
        courses_dir=request.store.courses_dir, course_id=request.course.id
    )
    if cards.exists():
        yield _make_member(
            path="cards/cards.jsonl", data=cards.read_bytes(), kind="cards"
        )


def _applied_options(request: ExportRequest) -> ExportOptions:
    document_ids = {
        document.id
        for document in iter_documents(
            courses_dir=request.store.courses_dir, course_id=request.course.id
        )
    }
    return ExportOptions(
        excluded_document_ids=request.options.excluded_document_ids & document_ids
    )


def write_package(target: Path | IO[bytes], request: ExportRequest) -> None:
    """Write a ZIP with a manifest; retain only one member's payload at a time.

    `target` is a path or an open binary file, which is left open.
    """
    inventory = []
    with ZipFile(file=target, mode="w", compression=ZIP_DEFLATED) as archive:
        for member in iter_package_members(request=request):
            archive.writestr(zinfo_or_arcname=member.entry.path, data=member.data)
            inventory.append(member.entry)
        manifest = Manifest(
            format_version=1,
            app_version=version(distribution_name="sbobina"),
            package_id=uuid4(),
            created_at=request.now,
            course=PackageCourse(label=request.course.label),
            inventory=tuple(inventory),
            options=_applied_options(request=request),
        )
        archive.writestr(
            zinfo_or_arcname="manifest.json", data=manifest.model_dump_json()
        )
