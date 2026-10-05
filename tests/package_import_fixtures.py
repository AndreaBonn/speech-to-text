import json
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from package_fixtures import seed_document, seed_generation_cards
from study_fixtures import transcript_fixture

from sbobina.course_registry import get_or_create
from sbobina.models import transcript_to_json
from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import ExportOptions, Manifest
from sbobina.study_models import StudyResult
from sbobina.study_render import STUDY_ADAPTER
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

IMPORT_TIME = datetime(2026, 10, 5, 12, tzinfo=UTC)
LECTURE_COUNT = 2


def make_package(directory: Path) -> Path:
    store = JobStore(data_dir=directory / "source")
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    transcript = transcript_to_json(transcript=transcript_fixture())
    for _ in range(LECTURE_COUNT):
        job = store.create(config=JobConfig(subject=course.label), source_name="Lesson")
        job_dir = store.jobs_dir / str(job.id)
        (job_dir / "audio.json").write_text(data=transcript, encoding="utf-8")
        (job_dir / "audio.corretto.json").write_text(data=transcript, encoding="utf-8")
        (job_dir / "audio.studio.json").write_bytes(data=study_bytes())
    seed_document(store=store, course=course)
    seed_generation_cards(store=store, course=course)
    target = directory / "course.sbobina.zip"
    write_package(
        target=target,
        request=ExportRequest(
            store=store, course=course, options=ExportOptions(), now=IMPORT_TIME
        ),
    )
    return target


def study_bytes() -> bytes:
    result = StudyResult(
        source_variant="corrected",
        source_revision="revision",
        model="test",
        prompt_version="studio-v2",
        generated_at=IMPORT_TIME.isoformat(),
        chapters=(),
        discarded=(),
        failed_blocks=(),
    )
    return STUDY_ADAPTER.dump_json(result)


def package_members(source: Path) -> dict[str, bytes]:
    with ZipFile(file=source) as archive:
        return {name: archive.read(name=name) for name in archive.namelist()}


def rewrite_package(source: Path, changes: dict[str, bytes | None]) -> Path:
    members = package_members(source=source)
    manifest = Manifest.model_validate_json(json_data=members.pop("manifest.json"))
    for name, payload in changes.items():
        if payload is None:
            members.pop(name)
        else:
            members[name] = payload
    target = source.with_name(name="changed.sbobina.zip")
    write_members(target=target, members=members, manifest=manifest)
    return target


def write_members(target: Path, members: dict[str, bytes], manifest: Manifest) -> None:
    inventory = tuple(
        entry.model_copy(
            update={
                "size": len(members[entry.path]),
                "sha256": sha256(members[entry.path]).hexdigest(),
            }
        )
        for entry in manifest.inventory
        if entry.path in members
    )
    with ZipFile(file=target, mode="w") as archive:
        for name, payload in members.items():
            archive.writestr(zinfo_or_arcname=name, data=payload)
        archive.writestr(
            zinfo_or_arcname="manifest.json",
            data=manifest.model_copy(update={"inventory": inventory}).model_dump_json(),
        )


def office_package(source: Path) -> Path:
    members = package_members(source=source)
    manifest = Manifest.model_validate_json(json_data=members.pop("manifest.json"))
    document = json.loads(members["documents/0/document.json"])
    document.update(kind="docx", filename="notes.docx")
    members["documents/0/document.json"] = json.dumps(obj=document).encode()
    original = BytesIO()
    with ZipFile(file=original, mode="w") as archive:
        archive.writestr(
            zinfo_or_arcname="[Content_Types].xml", data=b"wordprocessingml"
        )
        archive.writestr(zinfo_or_arcname="word/document.xml", data=b"<document />")
    members.pop("documents/0/original.txt")
    members["documents/0/original.docx"] = original.getvalue()
    inventory = tuple(
        entry.model_copy(
            update={"path": entry.path.replace("original.txt", "original.docx")}
        )
        for entry in manifest.inventory
    )
    target = source.with_name(name="office.sbobina.zip")
    write_members(
        target=target,
        members=members,
        manifest=manifest.model_copy(update={"inventory": inventory}),
    )
    return target


def snapshot(directory: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in directory.rglob("*")
    }
