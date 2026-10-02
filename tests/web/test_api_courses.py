import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStatus, LectureMeta
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
COURSES_URL = "/api/v1/courses"
JOBS_URL = "/api/v1/jobs"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


@pytest.mark.parametrize("status", list(JobStatus))
def test_patch_meta_preserves_job_bytes(
    client: TestClient, tmp_path: Path, status: JobStatus
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    store.update(record=record.model_copy(update={"status": status}))
    directory = store.jobs_dir / str(record.id)
    original = (directory / "job.json").read_bytes()

    response = client.patch(
        url=f"{JOBS_URL}/{record.id}/meta", json={"course": " Diritto  Privato "}
    )

    assert response.status_code == 200
    assert response.json() == {"data": {"course": "Diritto Privato"}}
    assert json.loads((directory / "meta.json").read_text(encoding="utf-8")) == {
        "course": "Diritto Privato"
    }
    assert (directory / "job.json").read_bytes() == original


@pytest.mark.parametrize("payload", [{"course": "x" * 101}, {"course": 123}, {}])
def test_patch_meta_rejects_invalid_course_with_field_error(
    client: TestClient, tmp_path: Path, payload: dict[str, object]
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    url = f"{JOBS_URL}/{record.id}/meta"
    assert client.patch(url=url, json={"course": "Fisica"}).status_code == 200

    response = client.patch(url=url, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["field"] == "course"
    assert store.read_meta(job_id=str(record.id)).course == "Fisica"


@pytest.mark.parametrize("course", [None, "", " \t"])
def test_patch_meta_cleared_course_restores_subject(
    client: TestClient, tmp_path: Path, course: str | None
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    url = f"{JOBS_URL}/{record.id}/meta"
    assert client.patch(url=url, json={"course": "Diritto"}).status_code == 200

    response = client.patch(url=url, json={"course": course})

    assert response.status_code == 200
    assert response.json() == {"data": {"course": None}}
    courses = client.get(url=COURSES_URL).json()["data"]
    assert [(item["key"], item["lecture_count"]) for item in courses] == [("fisica", 1)]


def test_patch_meta_rejects_foreign_origin(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    url = f"{JOBS_URL}/{record.id}/meta"
    assert client.patch(url=url, json={"course": "Fisica"}).status_code == 200

    response = client.patch(
        url=url, json={"course": "Diritto"}, headers={"Origin": "https://example.com"}
    )

    assert response.status_code == 403
    assert store.read_meta(job_id=str(record.id)).course == "Fisica"


def test_patch_meta_missing_job_returns_404(client: TestClient) -> None:
    response = client.patch(url=f"{JOBS_URL}/missing/meta", json={"course": "Fisica"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_meta_returns_the_saved_course(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    client.patch(url=f"{JOBS_URL}/{record.id}/meta", json={"course": "Fisica"})

    response = client.get(url=f"{JOBS_URL}/{record.id}/meta")

    assert response.status_code == 200
    assert response.json() == {"data": {"course": "Fisica"}}


def test_get_meta_defaults_to_none_without_a_meta_file(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())

    response = client.get(url=f"{JOBS_URL}/{record.id}/meta")

    assert response.status_code == 200
    assert response.json() == {"data": {"course": None}}


def test_get_meta_missing_job_returns_404(client: TestClient) -> None:
    response = client.get(url=f"{JOBS_URL}/missing/meta")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_courses_aggregates_all_lectures_before_pagination(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    for _ in range(21):
        store.create(config=JobConfig(subject="diritto privato"))
    latest = store.create(config=JobConfig(subject=" Diritto  Privato "))
    record = store.create(config=JobConfig(subject="Altro"))
    store.write_meta(job_id=str(record.id), meta=LectureMeta(course="Fisica"))

    response = client.get(url=COURSES_URL, params={"page": 1, "per_page": 10})

    assert response.status_code == 200
    assert response.json()["meta"] == {
        "page": 1,
        "per_page": 10,
        "total": 2,
        "total_pages": 1,
    }
    courses = response.json()["data"]
    assert [item["key"] for item in courses] == ["fisica", "diritto privato"]
    assert courses[1] == {
        "key": "diritto privato",
        "label": "Diritto Privato",
        "lecture_count": 22,
        "last_lecture_at": latest.created_at.isoformat(),
    }
    second = client.get(url=COURSES_URL, params={"page": 2, "per_page": 1}).json()
    assert second["data"] == [courses[1]]
    assert second["meta"] == {"page": 2, "per_page": 1, "total": 2, "total_pages": 2}


def test_courses_groups_missing_course_separately(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    store.create(config=JobConfig(subject="Senza corso"))
    store.create(config=JobConfig())
    courses = client.get(url=COURSES_URL).json()["data"]
    assert [(item["key"], item["label"]) for item in courses] == [
        ("", "Senza corso"),
        ("senza corso", "Senza corso"),
    ]


def test_courses_empty_archive_returns_complete_meta(client: TestClient) -> None:
    response = client.get(url=COURSES_URL, params={"page": 1, "per_page": 10})
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {"page": 1, "per_page": 10, "total": 0, "total_pages": 0},
    }


@pytest.mark.parametrize("query", [{"page": 0}, {"per_page": 0}, {"page": "bad"}])
def test_courses_rejects_invalid_pagination(
    client: TestClient, query: dict[str, object]
) -> None:
    response = client.get(
        url=COURSES_URL, params={key: str(value) for key, value in query.items()}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_courses_accepts_nfkc_expanded_legacy_subject(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="ﬃ" * 34))
    response = client.get(url=COURSES_URL)
    assert response.status_code == 200
    assert response.json()["data"][0]["key"] == "ffi" * 34
    filtered = client.get(url=JOBS_URL, params={"course": "ffi" * 34})
    assert [item["id"] for item in filtered.json()["data"]] == [str(record.id)]


@pytest.mark.parametrize("payload", ["Fisica", ["Fisica"], 3])
def test_patch_meta_reports_a_non_object_body_on_the_body_field(
    client: TestClient, tmp_path: Path, payload: object
) -> None:
    record = JobStore(data_dir=tmp_path).create(config=JobConfig())

    response = client.patch(url=f"{JOBS_URL}/{record.id}/meta", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body"
