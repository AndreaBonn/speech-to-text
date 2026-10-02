from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from starlette.requests import Request

from sbobina.course_registry import get_or_create, iter_courses, rename_key
from sbobina.settings import Settings
from sbobina.web.api_courses import RenameCourseRequest, rename_course, update_meta
from sbobina.web.app import create_app
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


def make_request(directory: Path) -> Request:
    app = create_app(settings=Settings(), data_dir=directory)
    return Request({"type": "http", "app": app})


def test_rename_course_concurrent_requests_keep_one_identity(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    store = JobStore(data_dir=tmp_path)
    store.create(config=JobConfig(subject="Fisica"))

    def rename(label: str) -> str:
        try:
            return str(
                rename_course(
                    key="fisica", body=RenameCourseRequest(label=label), request=request
                )["data"]["key"]
            )
        except NotFoundError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(rename, ["Fisica II", "Fisica III"]))
    courses = list(iter_courses(tmp_path / "courses"))
    assert len(courses) == 1
    assert sorted(results) == ["NOT_FOUND", courses[0].key]
    assert store.list(course_key=courses[0].key).total == 1


def test_rename_course_interrupted_retry_preserves_identity_and_allows_meta_repair(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    store = JobStore(data_dir=tmp_path)
    job = store.create(config=JobConfig(subject="Fisica"))
    original = get_or_create(tmp_path / "courses", key="fisica", label="Fisica")

    def fail_update(old: str, label: str) -> None:
        raise OSError("Interrupted lecture update")

    with pytest.raises(OSError):
        rename_key(
            tmp_path / "courses",
            old="fisica",
            new="Fisica II",
            update_lectures=fail_update,
        )
    with pytest.raises(ConflictError) as caught:
        rename_course(
            key="fisica", body=RenameCourseRequest(label="Fisica II"), request=request
        )
    assert caught.value.code == "COURSE_EXISTS"
    assert [(item.id, item.key) for item in iter_courses(tmp_path / "courses")] == [
        (original.id, "fisica ii")
    ]
    assert store.list(course_key="fisica").total == 1
    update_meta(job_id=str(job.id), body={"course": "Fisica II"}, request=request)
    assert store.list(course_key="fisica ii").total == 1


def test_rename_course_uncategorized_key_requires_named_course(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    with pytest.raises(ConflictError) as caught:
        rename_course(key="", body=RenameCourseRequest(label="Fisica"), request=request)
    assert caught.value.code == "COURSE_REQUIRED"
    assert list(iter_courses(tmp_path / "courses")) == []
