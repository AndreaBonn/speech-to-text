from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sbobina.package_models import (
    JOB_FIELD_EXPORT,
    ExportOptions,
    InventoryEntry,
    Manifest,
    PackageCourse,
    project_job,
)
from sbobina.web.job_models import (
    JobConfig,
    JobRecord,
    JobStage,
    JobStatus,
    StudyRun,
    StudyStatus,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def make_entry(path: str) -> InventoryEntry:
    return InventoryEntry(path=path, sha256="a" * 64, size=10, kind="transcript")


def test_inventory_path_transcript_is_accepted() -> None:
    assert make_entry(path="lectures/0/transcript.json").path == (
        "lectures/0/transcript.json"
    )


def test_inventory_path_parent_segment_is_rejected() -> None:
    with pytest.raises(ValidationError, match="parent"):
        make_entry(path="../x")


@pytest.mark.parametrize("path", ["/x", "C:/x"])
def test_inventory_path_absolute_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        make_entry(path=path)


def test_inventory_path_backslash_is_rejected() -> None:
    with pytest.raises(ValidationError, match="backslash"):
        make_entry(path=r"a\b")


@pytest.mark.parametrize("path", ["lectures/0/audio.mp3", "documents/0/original.WAV"])
def test_inventory_path_audio_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError, match="layout"):
        make_entry(path=path)


def test_manifest_round_trip_preserves_inventory_and_options() -> None:
    manifest = Manifest(
        format_version=1,
        app_version="0.1.0",
        package_id=uuid4(),
        created_at=NOW,
        course=PackageCourse(label="Fisica"),
        inventory=(make_entry(path="lectures/0/transcript.json"),),
        options=ExportOptions(excluded_document_ids=frozenset({"doc"})),
    )
    assert (
        Manifest.model_validate_json(json_data=manifest.model_dump_json()) == manifest
    )
    assert ExportOptions().excluded_document_ids == frozenset()


def test_manifest_newer_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="newer version"):
        Manifest.model_validate(obj={"format_version": 2})


def test_job_allowlist_classifies_every_field() -> None:
    assert JOB_FIELD_EXPORT.keys() == JobRecord.model_fields.keys()


@pytest.fixture
def record_with_local_state() -> JobRecord:
    return JobRecord(
        id=uuid4(),
        status=JobStatus.DONE,
        stage=JobStage.DONE,
        config=JobConfig(subject="Fisica"),
        created_at=NOW,
        updated_at=NOW,
        pid=123,
        error={"message": "/private/path"},
        source_name="Lecture.m4a",
        study=StudyRun(
            status=StudyStatus.FAILED, updated_at=NOW, error={"path": "secret"}
        ),
    )


@pytest.mark.parametrize("imported", [False, True])
def test_project_job_keeps_identity_without_excluded_fields(
    imported: bool, record_with_local_state: JobRecord
) -> None:
    import_id = str(uuid4()) if imported else None
    record = record_with_local_state.model_copy(
        update={"imported": imported, "import_id": import_id}
    )
    projection = project_job(record=record)
    assert projection == {
        "id": str(record.id),
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
        "source_name": "Lecture.m4a",
    }
    # import_id names a course on this machine; the recipient's import sets
    # its own, so neither field travels in the package.
    assert "import_id" not in projection
    assert "imported" not in projection
    assert all(
        field not in projection
        for field, exported in JOB_FIELD_EXPORT.items()
        if not exported
    )
