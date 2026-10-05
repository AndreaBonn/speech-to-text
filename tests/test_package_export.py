import json
import logging
from hashlib import sha256
from pathlib import Path, PurePosixPath

import pytest
from package_fixtures import (
    NOW,
    ORIGINAL,
    TEXT,
    TRANSCRIPT,
    PackageFixture,
    seed_package,
)

from sbobina.course_registry import get_or_create
from sbobina.package_export import ExportRequest, iter_package_members, write_package
from sbobina.package_models import ExportOptions, Manifest
from sbobina.web.card_store import cards_path, reviews_path
from sbobina.web.document_store import document_dir
from sbobina.web.generation_store import generation_dir
from sbobina.web.job_models import JobConfig, JobStatus


@pytest.fixture
def course_data(tmp_path: Path) -> PackageFixture:
    return seed_package(tmp_path=tmp_path)


def make_request(
    data: PackageFixture, excluded: frozenset[str] = frozenset()
) -> ExportRequest:
    return ExportRequest(
        store=data.store,
        course=data.course,
        now=NOW,
        options=ExportOptions(excluded_document_ids=excluded),
    )


def test_inventory_excludes_audio_and_personal_data(
    course_data: PackageFixture,
) -> None:
    members = list(iter_package_members(request=make_request(data=course_data)))
    assert (
        next(
            member.data
            for member in members
            if member.entry.path == "lectures/0/transcript.json"
        )
        == TRANSCRIPT
    )
    forbidden_suffixes = {
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".webm",
    }
    for member in members:
        path = PurePosixPath(member.entry.path)
        assert path.suffix.lower() not in forbidden_suffixes
        assert not {"practice", "attempts", "reviews", "chats", "chat"}.intersection(
            path.parts
        )
        assert path.name != "reviews.jsonl"


def test_inventory_documents_default_includes_text_and_original(
    course_data: PackageFixture,
) -> None:
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=make_request(data=course_data))
    }
    for index in range(2):
        assert contents[f"documents/{index}/text.json"] == TEXT
        assert contents[f"documents/{index}/original.txt"] == ORIGINAL
        assert (
            json.loads(contents[f"documents/{index}/document.json"])["id"]
            == course_data.document_ids[index]
        )


def test_inventory_deselection_omits_both_payloads_only_for_selected_document(
    course_data: PackageFixture,
) -> None:
    request = make_request(
        data=course_data, excluded=frozenset({course_data.document_ids[0]})
    )
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=request)
    }
    assert contents["documents/1/text.json"] == TEXT
    assert contents["documents/1/original.txt"] == ORIGINAL
    assert (
        json.loads(contents["documents/0/document.json"])["id"]
        == course_data.document_ids[0]
    )
    assert "documents/0/text.json" not in contents
    assert "documents/0/original.txt" not in contents


def test_inventory_hashes_and_sizes_match_contents(course_data: PackageFixture) -> None:
    members = list(iter_package_members(request=make_request(data=course_data)))
    assert len(members) == 12
    for member in members:
        assert member.entry.sha256 == sha256(member.data).hexdigest()
        assert member.entry.size == len(member.data)


def test_inventory_preserves_generations_and_card_events_without_fsrs(
    course_data: PackageFixture,
) -> None:
    store, course = course_data.store, course_data.course
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=make_request(data=course_data))
    }
    generation = next(
        generation_dir(courses_dir=store.courses_dir, course_id=course.id).glob(
            "*.json"
        )
    )
    assert contents["generations/0.json"] == generation.read_bytes()
    assert (
        contents["cards/cards.jsonl"]
        == cards_path(courses_dir=store.courses_dir, course_id=course.id).read_bytes()
    )
    events = [json.loads(line) for line in contents["cards/cards.jsonl"].splitlines()]
    assert events[0]["dedup_key"] == "preserve-this-key"
    assert len(events) == 2
    assert all("fsrs" not in event for event in events)
    reviews = reviews_path(
        courses_dir=store.courses_dir, course_id=course.id
    ).read_bytes()
    assert b'"fsrs"' in reviews
    assert "cards/reviews.jsonl" not in contents


def test_inventory_scopes_lectures_by_label_and_other_content_by_id(
    course_data: PackageFixture,
) -> None:
    other = seed_package(tmp_path=course_data.store.jobs_dir.parent, label="Other")
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=make_request(data=course_data))
    }
    assert json.loads(contents["lectures/0/meta.json"])["id"] == course_data.job_id
    assert (
        json.loads(contents["documents/0/document.json"])["course_id"]
        == course_data.course.id
    )
    assert len(contents) == 12
    for path in contents:
        assert other.course.id not in path
        assert other.job_id not in path
        if path.startswith(("lectures/", "documents/", "generations/")):
            assert PurePosixPath(path).parts[1].split(".")[0].isdigit()


def test_inventory_optional_files_absent_keeps_required_files(
    course_data: PackageFixture,
) -> None:
    directory = course_data.store.jobs_dir / course_data.job_id
    (directory / "audio.corretto.json").unlink()
    (directory / "audio.studio.json").unlink()
    document = document_dir(
        courses_dir=course_data.store.courses_dir,
        course_id=course_data.course.id,
        doc_id=course_data.document_ids[0],
    )
    (document / "text.json").unlink()
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=make_request(data=course_data))
    }
    assert contents["lectures/0/transcript.json"] == TRANSCRIPT
    assert contents["documents/0/original.txt"] == ORIGINAL
    assert contents["documents/1/text.json"] == TEXT
    assert "lectures/0/corrected.json" not in contents
    assert "lectures/0/study.json" not in contents
    assert "documents/0/text.json" not in contents


def test_inventory_missing_required_transcript_raises(
    course_data: PackageFixture,
) -> None:
    # A finished lecture must have its transcript: losing it is not a skip.
    store = course_data.store
    record = store.get(job_id=course_data.job_id)
    store.update(record=record.model_copy(update={"status": JobStatus.DONE}))
    (store.jobs_dir / course_data.job_id / "audio.json").unlink()
    with pytest.raises(FileNotFoundError):
        list(iter_package_members(request=make_request(data=course_data)))


@pytest.mark.parametrize(
    "status", [status for status in JobStatus if status is not JobStatus.DONE]
)
def test_inventory_skips_course_lecture_never_transcribed(
    course_data: PackageFixture, status: JobStatus, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(level=logging.INFO, logger="sbobina.package_export")
    store = course_data.store
    untranscribed = store.create(config=JobConfig(subject="Fisica"))
    store.update(record=untranscribed.model_copy(update={"status": status}))
    contents = {
        member.entry.path: member.data
        for member in iter_package_members(request=make_request(data=course_data))
    }
    assert json.loads(contents["lectures/0/meta.json"])["id"] == course_data.job_id
    assert not any(path.startswith("lectures/1/") for path in contents)
    assert f"Export skips lecture {untranscribed.id} ({status})" in caplog.text


def test_write_package_empty_course_writes_empty_manifest(tmp_path: Path) -> None:
    from zipfile import ZipFile

    from sbobina.web.job_store import JobStore

    store = JobStore(data_dir=tmp_path)
    course = get_or_create(courses_dir=store.courses_dir, key="empty", label="Empty")
    request = ExportRequest(
        store=store, course=course, options=ExportOptions(), now=NOW
    )
    path = tmp_path / "empty.zip"
    write_package(target=path, request=request)
    with ZipFile(file=path) as archive:
        assert archive.namelist() == ["manifest.json"]
        manifest = Manifest.model_validate_json(
            json_data=archive.read(name="manifest.json")
        )
    assert manifest.inventory == ()
    assert manifest.course.label == "Empty"


def test_write_package_manifest_matches_zip_and_applied_options(
    course_data: PackageFixture, tmp_path: Path
) -> None:
    from zipfile import ZipFile

    request = make_request(
        data=course_data, excluded=frozenset({course_data.document_ids[0], "unknown"})
    )
    path = tmp_path / "course.zip"
    write_package(target=path, request=request)
    with ZipFile(file=path) as archive:
        manifest = Manifest.model_validate_json(
            json_data=archive.read(name="manifest.json")
        )
        assert set(archive.namelist()) == {"manifest.json"} | {
            entry.path for entry in manifest.inventory
        }
        assert len(manifest.inventory) == 10
        for entry in manifest.inventory:
            content = archive.read(name=entry.path)
            assert sha256(content).hexdigest() == entry.sha256
            assert len(content) == entry.size
    assert manifest.options.excluded_document_ids == {course_data.document_ids[0]}
    assert request.options.excluded_document_ids == {
        course_data.document_ids[0],
        "unknown",
    }
    assert manifest.created_at == NOW
    assert manifest.course.label == "Fisica"
