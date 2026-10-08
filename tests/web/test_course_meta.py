from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from sbobina.courses import effective_course
from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobConfig, JobStatus
from sbobina.web.job_store import JobStore


def test_read_meta_missing_file_falls_back_to_subject(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject=" Diritto  Privato "))
    meta = store.read_meta(job_id=str(record.id))

    assert meta.course is None
    assert effective_course(course=meta.course, subject=record.config.subject) == (
        "Diritto Privato"
    )
    assert store.list(course_key="diritto privato").items == [record]
    assert sorted(
        path.name for path in (store.jobs_dir / str(record.id)).iterdir()
    ) == ["job.json"]


@pytest.mark.parametrize("course", ["  Diritto   Privato ", "Ｄiritto Privato"])
def test_lecture_meta_normalizes_course(course: str) -> None:
    from sbobina.web.job_models import LectureMeta

    assert LectureMeta(course=course).course == "Diritto Privato"


@pytest.mark.parametrize("course", [None, "", " \t"])
def test_lecture_meta_empty_course_is_none(course: str | None) -> None:
    from sbobina.web.job_models import LectureMeta

    assert LectureMeta(course=course).course is None
    assert LectureMeta(course="Fisica").course == "Fisica"


def test_lecture_meta_rejects_overlong_course() -> None:
    from sbobina.web.job_models import LectureMeta

    assert LectureMeta(course="x" * 100).course == "x" * 100
    with pytest.raises(PydanticValidationError) as caught:
        LectureMeta(course="x" * 101)
    assert caught.value.errors()[0]["loc"] == ("course",)


def test_list_course_filter_counts_matches_before_pagination(tmp_path: Path) -> None:
    from sbobina.web.job_models import LectureMeta

    store = JobStore(data_dir=tmp_path)
    subjects = ["diritto privato", "Fisica", "Altro", None, "Diritto Privato"]
    records = [store.create(config=JobConfig(subject=subject)) for subject in subjects]
    store.write_meta(
        job_id=str(records[1].id), meta=LectureMeta(course="Diritto Privato")
    )
    store.write_meta(job_id=str(records[4].id), meta=LectureMeta(course="Fisica"))

    first = store.list(page=1, per_page=1, course_key="diritto privato")
    second = store.list(page=2, per_page=1, course_key="diritto privato")
    assert (first.items, second.items) == ([records[1]], [records[0]])
    assert (first.total, first.total_pages, first.page, first.per_page) == (2, 2, 1, 1)
    assert second.total == 2


def test_list_empty_course_key_selects_unassigned_jobs(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    unassigned = store.create(config=JobConfig())
    store.create(config=JobConfig(subject="Fisica"))

    result = store.list(course_key="")

    assert result.items == [unassigned]
    assert result.total == 1


def test_list_unknown_course_key_excludes_existing_jobs(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig(subject="Fisica"))

    result = store.list(course_key="inesistente")

    assert (result.items, result.total) == ([], 0)
    assert store.list(course_key="fisica").items == [job]


def test_list_without_course_filter_includes_all_courses(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    jobs = [
        store.create(config=JobConfig(subject=subject))
        for subject in [None, "Fisica", "Diritto"]
    ]

    result = store.list()

    assert result.items == list(reversed(jobs))
    assert result.total == 3


def test_write_meta_round_trip_preserves_job_and_null_restores_fallback(
    tmp_path: Path,
) -> None:
    from sbobina.web.job_models import LectureMeta

    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    job_path = store.jobs_dir / str(record.id) / "job.json"
    original = job_path.read_bytes()
    store.write_meta(job_id=str(record.id), meta=LectureMeta(course="Diritto"))
    assert store.read_meta(job_id=str(record.id)).course == "Diritto"
    assert store.list(course_key="diritto").items == [record]
    store.write_meta(job_id=str(record.id), meta=LectureMeta(course=None))
    assert store.read_meta(job_id=str(record.id)).course is None
    assert store.list(course_key="fisica").items == [record]
    assert job_path.read_bytes() == original


def test_write_meta_concurrent_update_preserves_both_files(tmp_path: Path) -> None:
    from sbobina.web.job_models import LectureMeta

    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    barrier = Barrier(parties=2, timeout=5)

    def write_user_meta() -> None:
        barrier.wait()
        store.write_meta(job_id=str(record.id), meta=LectureMeta(course="Diritto"))

    def update_supervisor_record() -> None:
        barrier.wait()
        store.update(record=record.model_copy(update={"status": JobStatus.RUNNING}))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_user_meta),
            executor.submit(update_supervisor_record),
        ]
        for future in futures:
            future.result(timeout=5)
    assert store.read_meta(job_id=str(record.id)).course == "Diritto"
    updated = store.get(job_id=str(record.id))
    assert updated.status == JobStatus.RUNNING
    assert updated.config.subject == "Fisica"
    assert set(updated.model_dump()) == set(record.model_dump())


@pytest.mark.parametrize("job_id", ["../escape", str(uuid4())])
def test_meta_operations_reject_missing_job(tmp_path: Path, job_id: str) -> None:
    from sbobina.web.job_models import LectureMeta

    store = JobStore(data_dir=tmp_path)
    with pytest.raises(NotFoundError):
        store.read_meta(job_id=job_id)
    with pytest.raises(NotFoundError):
        store.write_meta(job_id=job_id, meta=LectureMeta(course="Fisica"))


def test_write_meta_revalidates_before_replacing_file(tmp_path: Path) -> None:
    from sbobina.web.job_models import LectureMeta

    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    valid = LectureMeta(course="Fisica")
    store.write_meta(job_id=str(record.id), meta=valid)
    with pytest.raises(PydanticValidationError):
        store.write_meta(
            job_id=str(record.id), meta=valid.model_copy(update={"course": "x" * 101})
        )
    assert store.read_meta(job_id=str(record.id)) == valid


def test_read_meta_corrupt_file_propagates_validation_error(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    assert store.read_meta(job_id=str(record.id)).course is None
    (store.jobs_dir / str(record.id) / "meta.json").write_text(
        "broken", encoding="utf-8"
    )
    with pytest.raises(PydanticValidationError):
        store.read_meta(job_id=str(record.id))
