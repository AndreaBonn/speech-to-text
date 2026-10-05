import json
import logging
import shutil
from pathlib import Path

import pytest
from package_fixtures import ORIGINAL
from package_import_fixtures import IMPORT_TIME, LECTURE_COUNT, make_package, snapshot
from study_fixtures import transcript_fixture

from sbobina.course_registry import iter_courses
from sbobina.models import load_transcript
from sbobina.package_import import PackageStorageError, import_package
from sbobina.web.card_store import load_cards
from sbobina.web.document_store import document_dir, iter_documents, read_text
from sbobina.web.generation_store import iter_generations
from sbobina.web.job_models import JobRecord, JobStage, JobStatus
from sbobina.web.job_store import JobStore


def assert_lecture(directory: Path, course_id: str) -> None:
    assert load_transcript(path=directory / "audio.json") == transcript_fixture()
    assert (
        load_transcript(path=directory / "audio.corretto.json") == transcript_fixture()
    )
    record = JobRecord.model_validate_json(
        json_data=(directory / "job.json").read_text(encoding="utf-8")
    )
    assert record.imported is True
    assert record.import_id == course_id
    assert record.status == JobStatus.DONE
    assert record.stage == JobStage.DONE
    assert (directory / "audio.studio.json").is_file()


def test_import_package_empty_data_restores_course_lessons_documents(
    tmp_path: Path,
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    result = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    store = JobStore(data_dir=data)
    assert list(iter_courses(courses_dir=store.courses_dir)) == [result.course]
    jobs = list(store.iter_records())
    assert len(jobs) == LECTURE_COUNT
    for job in jobs:
        directory = store.jobs_dir / str(job.id)
        assert job.config.subject == result.course.label
        assert_lecture(directory=directory, course_id=result.course.id)
    documents = list(
        iter_documents(courses_dir=store.courses_dir, course_id=result.course.id)
    )
    assert len(documents) == 1
    directory = document_dir(
        courses_dir=store.courses_dir,
        course_id=result.course.id,
        doc_id=documents[0].id,
    )
    assert (directory / "original.txt").read_bytes() == ORIGINAL
    assert read_text(doc_dir=directory).pages[0].text == ORIGINAL.decode()
    assert len(list(iter_generations(courses_dir=store.courses_dir))) == 1
    assert (
        len(load_cards(courses_dir=store.courses_dir, course_id=result.course.id)) == 1
    )


@pytest.mark.parametrize("failure_at", [1, 2, LECTURE_COUNT + 1])
def test_import_package_second_rename_failure_restores_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_at: int
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    first = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    before = snapshot(directory=data)
    rename = Path.rename
    destinations: list[Path] = []

    def fail_rename(self: Path, target: Path) -> Path:
        destinations.append(target)
        if len(destinations) == failure_at:
            raise OSError("injected rename failure")
        return rename(self, target=target)

    monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(PackageStorageError) as raised:
        import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert str(raised.value.__cause__) == "injected rename failure"
    assert raised.value.code == "PACKAGE_STORAGE_FAILED"
    assert len(destinations) == failure_at
    assert snapshot(directory=data) == before
    assert (data / "courses" / first.course.id / "course.json").is_file()
    assert destinations[0].parent == data / "jobs"
    assert list(data.rglob(".import-*")) == []


def test_import_package_reimport_creates_new_course_with_warning(
    tmp_path: Path,
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    first = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    second = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert first.warning is None
    assert second.warning == f"già importato il {IMPORT_TIME.isoformat()}"
    assert len({first.course.id, second.course.id}) == 2
    assert len({first.course.key, second.course.key}) == 2
    assert len(list(iter_courses(courses_dir=data / "courses"))) == 2
    provenance = json.loads(
        (data / "courses" / second.course.id / "imported_from.json").read_text()
    )
    assert provenance["package_id"] == second.imported_from.package_id
    assert provenance["ids"] == second.imported_from.to_dict()["ids"]
    assert provenance["imported_at"] == IMPORT_TIME.isoformat()


def test_import_package_publishes_lectures_before_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    rename = Path.rename
    destinations: list[Path] = []

    def observe_rename(self: Path, target: Path) -> Path:
        assert list(iter_courses(courses_dir=data / "courses")) == []
        assert len(list(JobStore(data_dir=data).iter_records())) == len(destinations)
        destinations.append(target)
        return rename(self, target=target)

    monkeypatch.setattr(Path, "rename", observe_rename)
    result = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert [path.parent.name for path in destinations] == ["jobs", "jobs", "courses"]
    assert list(iter_courses(courses_dir=data / "courses")) == [result.course]
    assert len(list(JobStore(data_dir=data).iter_records())) == LECTURE_COUNT
    assert list(data.rglob(".import-*")) == []


def test_import_package_second_rename_failure_removes_new_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    rename = Path.rename
    published: list[Path] = []
    before = snapshot(directory=tmp_path)

    def fail_second(self: Path, target: Path) -> Path:
        if published:
            assert (published[0] / "job.json").is_file()
            raise OSError("second rename")
        published.append(target)
        return rename(self, target=target)

    monkeypatch.setattr(Path, "rename", fail_second)
    with pytest.raises(PackageStorageError, match="Could not write") as raised:
        import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert str(raised.value.__cause__) == "second rename"
    assert len(published) == 1
    assert snapshot(directory=tmp_path) == before
    assert not data.exists()


def test_import_package_failed_rollback_keeps_the_original_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A rollback step that fails is logged; the error the user sees still
    # names what broke the import, not the cleanup.
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    rename = Path.rename

    def fail_second_rename(self: Path, target: Path) -> Path:
        if target.parent == data / "jobs" and any((data / "jobs").glob("[!.]*")):
            raise OSError("injected rename failure")
        return rename(self, target=target)

    def fail_rmtree(path: Path) -> None:
        raise OSError(f"injected cleanup failure: {Path(path).name}")

    monkeypatch.setattr(Path, "rename", fail_second_rename)
    monkeypatch.setattr(shutil, "rmtree", fail_rmtree)
    with (
        caplog.at_level(level=logging.ERROR, logger="sbobina.package_import_commit"),
        pytest.raises(PackageStorageError) as raised,
    ):
        import_package(source=source, data_dir=data, now=IMPORT_TIME)

    assert str(raised.value.__cause__) == "injected rename failure"
    assert "injected cleanup failure" in caplog.text


def test_import_package_staging_cleanup_failure_keeps_a_published_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Once the course is published the import has succeeded: leftover staging
    # is logged, never turned into an error that invites a duplicate retry.
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"

    rmdir = Path.rmdir

    def fail_staging_rmdir(self: Path) -> None:
        if self.name.startswith(".import-"):
            raise OSError("injected cleanup failure")
        rmdir(self)

    monkeypatch.setattr(Path, "rmdir", fail_staging_rmdir)
    with caplog.at_level(level=logging.WARNING, logger="sbobina.package_import_commit"):
        result = import_package(source=source, data_dir=data, now=IMPORT_TIME)

    assert (data / "courses" / result.course.id / "course.json").is_file()
    assert "injected cleanup failure" in caplog.text
