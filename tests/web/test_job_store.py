import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import JsonValue

from sbobina.web.errors import NotFoundError, ValidationError
from sbobina.web.job_models import JobConfig, JobStage, JobStatus
from sbobina.web.job_store import JobStore


def test_create_get_and_update_persist_records(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    original = store.create(config=JobConfig(subject="Fisica"))
    assert original.id.version == 4
    assert original.status == JobStatus.QUEUED
    changed = original.model_copy(
        update={"status": JobStatus.RUNNING, "stage": JobStage.TRANSCRIBING, "pid": 123}
    )
    updated = store.update(record=changed)
    assert JobStore(data_dir=tmp_path).get(job_id=str(original.id)) == updated
    assert updated.status == JobStatus.RUNNING
    assert updated.created_at == original.created_at
    assert updated.updated_at >= original.updated_at
    assert original.pid is None
    assert updated.pid == 123


def test_list_paginates_in_creation_order(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    jobs = [store.create(config=JobConfig()) for _ in range(25)]
    page = store.list(page=3, per_page=10)
    assert page.items == list(reversed(jobs[:5]))
    assert (page.page, page.per_page, page.total, page.total_pages) == (3, 10, 25, 3)
    assert store.list(page=4, per_page=10).items == []


def test_empty_store_and_invalid_pagination(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    result = store.list(page=1, per_page=10)
    assert (result.items, result.total, result.total_pages) == ([], 0, 0)
    for page, size in [(0, 10), (1, 0)]:
        with pytest.raises(ValidationError):
            store.list(page=page, per_page=size)


def test_progress_round_trips_and_delete_removes_job(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    job_id = str(job.id)
    assert store.read_progress(job_id=job_id) == {}
    progress: dict[str, JsonValue] = {
        "stage": "transcribing",
        "progress": 0.4,
        "audio_s": 20,
        "elapsed_s": 2,
    }
    store.write_progress(job_id=job_id, progress=progress)
    assert store.read_progress(job_id=job_id) == progress
    store.delete(job_id=job_id)
    with pytest.raises(NotFoundError):
        store.get(job_id=job_id)


@pytest.mark.parametrize(
    "job_id", ["../outside", "not-a-uuid", "", "00000000-0000-0000-0000-000000000000"]
)
def test_invalid_ids_fail_before_filesystem_access(tmp_path: Path, job_id: str) -> None:
    store = JobStore(data_dir=tmp_path)
    with patch.object(Path, "is_dir", side_effect=AssertionError("Unexpected I/O")):
        with pytest.raises(NotFoundError):
            store.get(job_id=job_id)
        with pytest.raises(NotFoundError):
            store.delete(job_id=job_id)
        with pytest.raises(NotFoundError):
            store.read_progress(job_id=job_id)
        with pytest.raises(NotFoundError):
            store.write_progress(job_id=job_id, progress={})


def test_missing_job_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        JobStore(data_dir=tmp_path).get(job_id=str(uuid4()))


def test_failed_atomic_update_preserves_previous_json(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    changed = job.model_copy(update={"status": JobStatus.DONE})
    with (
        patch("sbobina.web.job_store.os.replace", side_effect=OSError("Disk failure")),
        pytest.raises(OSError, match="Disk failure"),
    ):
        store.update(record=changed)
    assert store.get(job_id=str(job.id)) == job
    assert list((tmp_path / "jobs" / str(job.id)).iterdir()) == [
        tmp_path / "jobs" / str(job.id) / "job.json"
    ]


def test_atomic_write_retries_permission_error_then_succeeds(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    changed = job.model_copy(update={"status": JobStatus.DONE})
    real_replace = os.replace
    attempts: list[int] = []

    def flaky_replace(source: Path, destination: Path) -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("locked")
        real_replace(source, destination)

    with (
        patch("sbobina.web.job_store.os.replace", side_effect=flaky_replace) as replace,
        patch("sbobina.web.job_store.time.sleep") as sleep,
    ):
        store.update(record=changed)
    assert replace.call_count == 3
    assert sleep.call_count == 2
    assert store.get(job_id=str(job.id)).status == JobStatus.DONE


def test_atomic_write_gives_up_after_max_permission_errors(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    changed = job.model_copy(update={"status": JobStatus.DONE})
    with (
        patch(
            "sbobina.web.job_store.os.replace",
            side_effect=PermissionError("locked"),
        ) as replace,
        patch("sbobina.web.job_store.time.sleep"),
        pytest.raises(PermissionError),
    ):
        store.update(record=changed)
    assert replace.call_count == 3
    assert store.get(job_id=str(job.id)) == job


def test_update_preserves_creation_time_and_validates_record(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    changed = job.model_copy(update={"created_at": job.created_at + timedelta(days=1)})
    assert store.update(record=changed).created_at == job.created_at
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        store.update(record=job.model_copy(update={"status": "unknown"}))


def test_corrupt_json_is_not_silently_skipped(tmp_path: Path) -> None:
    from pydantic import ValidationError as PydanticValidationError

    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    (tmp_path / "jobs" / str(job.id) / "job.json").write_text(
        "broken", encoding="utf-8"
    )
    with pytest.raises(PydanticValidationError):
        store.list(page=1, per_page=10)


def test_corrupt_progress_json_is_not_silently_reset(tmp_path: Path) -> None:
    from pydantic import ValidationError as PydanticValidationError

    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig())
    (tmp_path / "jobs" / str(job.id) / "progress.json").write_text(
        "broken", encoding="utf-8"
    )

    with pytest.raises(PydanticValidationError):
        store.read_progress(job_id=str(job.id))


def _imported(store: JobStore, course_id: str, subject: str) -> str:
    record = store.create(config=JobConfig(subject=subject))
    store.update(
        record=record.model_copy(update={"imported": True, "import_id": course_id})
    )
    return str(record.id)


def test_orphan_imported_lecture_is_hidden_and_removed(tmp_path: Path) -> None:
    # T092: an import killed after renaming its lectures but before its course
    # leaves lectures whose course is not in the registry.
    store = JobStore(data_dir=tmp_path)
    normal = str(store.create(config=JobConfig(subject="Storia")).id)
    kept_course = str(uuid4())
    (store.courses_dir / kept_course).mkdir(parents=True)
    (store.courses_dir / kept_course / "course.json").write_text("{}", encoding="utf-8")
    kept = _imported(store=store, course_id=kept_course, subject="Fisica")
    orphan = _imported(store=store, course_id=str(uuid4()), subject="Chimica")

    listed = {str(record.id) for record in store.list(per_page=10).items}
    iterated = {str(record.id) for record in store.iter_records()}
    removed = store.remove_orphan_imports()

    assert listed == iterated == {normal, kept}
    assert removed == [orphan]
    assert not (store.jobs_dir / orphan).exists()
    assert (store.jobs_dir / normal).is_dir() and (store.jobs_dir / kept).is_dir()
    assert store.remove_orphan_imports() == []
