"""Write domain records to generated staging paths, never to package paths."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from pydantic import TypeAdapter

from sbobina.card_models import dump_card_event
from sbobina.course_registry import CourseRecord
from sbobina.document_sniff import READ_CHUNK_BYTES, sniff_document
from sbobina.generation_models import dump_generation
from sbobina.package_import_commit import ImportStaging
from sbobina.package_import_load import DOCUMENT_ADAPTER, LoadedDocument, LoadedPackage
from sbobina.package_remap_types import PackageJob, RemappedPackage
from sbobina.package_validate import PackageInvalidError
from sbobina.web.card_store import cards_path
from sbobina.web.document_store import (
    DOCUMENT_FILENAME,
    TEXT_FILENAME,
    document_dir,
    original_path,
)
from sbobina.web.generation_store import generation_path
from sbobina.web.job_models import (
    JobConfig,
    JobRecord,
    JobStage,
    JobStatus,
    LectureMeta,
)

COURSE_ADAPTER = TypeAdapter(CourseRecord)
PROVENANCE_FILENAME = "imported_from.json"


@dataclass(frozen=True, kw_only=True)
class StageRequest:
    loaded: LoadedPackage
    remapped: RemappedPackage
    staging: ImportStaging
    now: datetime


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data=data)


def _job_record(job: PackageJob, course: CourseRecord) -> JobRecord:
    return JobRecord(
        id=UUID(hex=job.id),
        status=JobStatus.DONE,
        stage=JobStage.DONE,
        config=JobConfig(subject=course.label),
        imported=True,
        import_id=course.id,
        source_name=job.source_name,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _stage_lectures(request: StageRequest) -> None:
    course = request.remapped.course
    for loaded, job in zip(
        request.loaded.lectures, request.remapped.content.jobs, strict=True
    ):
        directory = request.staging.jobs / job.id
        record = _job_record(job=job, course=course)
        files = loaded.files | {
            "job.json": record.model_dump_json().encode(encoding="utf-8"),
            "meta.json": LectureMeta(course=course.label)
            .model_dump_json()
            .encode(encoding="utf-8"),
        }
        for name, payload in files.items():
            _write(path=directory / name, data=payload)


def _stage_original(loaded: LoadedDocument, directory: Path) -> None:
    if loaded.original is None:
        return
    target = original_path(doc_dir=directory, kind=loaded.record.kind)
    # Sniff needs a path for Office limits and whole-file UTF-8 validation.
    with NamedTemporaryFile(dir=directory, delete_on_close=False) as temporary:
        temporary.write(loaded.original)
        temporary.close()
        kind = sniff_document(
            head=loaded.original[:READ_CHUNK_BYTES],
            path=Path(temporary.name),
            filename=target.name,
        )
        if kind != loaded.record.kind:
            raise PackageInvalidError("Original document failed content sniffing")
    _write(path=target, data=loaded.original)


def _stage_documents(request: StageRequest) -> None:
    for loaded, document in zip(
        request.loaded.documents, request.remapped.content.documents, strict=True
    ):
        directory = document_dir(
            courses_dir=request.staging.courses,
            course_id=request.remapped.course.id,
            doc_id=document.id,
        )
        _write(
            path=directory / DOCUMENT_FILENAME,
            data=DOCUMENT_ADAPTER.dump_json(document),
        )
        if loaded.text is not None:
            _write(path=directory / TEXT_FILENAME, data=loaded.text)
        _stage_original(loaded=loaded, directory=directory)


def stage_package(request: StageRequest) -> None:
    course = request.remapped.course
    directory = request.staging.courses / course.id
    _write(path=directory / "course.json", data=COURSE_ADAPTER.dump_json(course))
    provenance = request.remapped.imported_from.to_dict() | {
        "imported_at": request.now.isoformat()
    }
    _write(
        path=directory / PROVENANCE_FILENAME,
        data=json.dumps(obj=provenance).encode(encoding="utf-8"),
    )
    _stage_lectures(request=request)
    _stage_documents(request=request)
    for generation in request.remapped.content.generations:
        path = generation_path(
            courses_dir=request.staging.courses,
            course_id=course.id,
            gen_id=generation.id,
        )
        _write(
            path=path, data=dump_generation(record=generation).encode(encoding="utf-8")
        )
    path = cards_path(courses_dir=request.staging.courses, course_id=course.id)
    data = "".join(
        dump_card_event(event=event) for event in request.remapped.content.cards
    )
    _write(path=path, data=data.encode(encoding="utf-8"))
