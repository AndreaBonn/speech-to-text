from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.course_registry import find_by_key, get_or_create
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
COURSES_URL = "/api/v1/courses"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def test_list_courses_registry_only_course_has_zero_lectures(
    client: TestClient, tmp_path: Path
) -> None:
    course = get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    response = client.get(COURSES_URL)
    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "key": "fisica",
                "label": "Fisica",
                "lecture_count": 0,
                "last_lecture_at": course.created_at.isoformat(),
            }
        ],
        "meta": {"page": 1, "per_page": 20, "total": 1, "total_pages": 1},
    }


def test_list_courses_union_paginates_without_duplicates(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    get_or_create(tmp_path / "courses", key="diritto", label="Diritto")

    first = client.get(COURSES_URL, params={"per_page": 1}).json()
    second = client.get(COURSES_URL, params={"page": 2, "per_page": 1}).json()

    assert first["meta"] == {"page": 1, "per_page": 1, "total": 2, "total_pages": 2}
    assert first["data"][0]["key"] == "diritto"
    assert second["data"] == [
        {
            "key": "fisica",
            "label": "Fisica",
            "lecture_count": 1,
            "last_lecture_at": lecture.created_at.isoformat(),
        }
    ]


def test_rename_course_moves_effective_course_and_preserves_job(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    legacy = store.create(config=JobConfig(subject="Fisica"))
    explicit = store.create(config=JobConfig(subject="Altro"))
    other = store.create(config=JobConfig(subject="Fisica"))
    store.write_meta(job_id=str(explicit.id), meta=LectureMeta(course="FISICA"))
    store.write_meta(job_id=str(other.id), meta=LectureMeta(course="Diritto"))
    course = get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    path = store.jobs_dir / str(legacy.id) / "job.json"
    original = path.read_bytes()

    response = client.post(
        f"{COURSES_URL}/fisica/rename", json={"label": " Fisica  II "}
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == course.id
    assert response.json()["data"]["key"] == "fisica ii"
    assert store.read_meta(job_id=str(legacy.id)).course == "Fisica II"
    assert store.read_meta(job_id=str(explicit.id)).course == "Fisica II"
    assert store.read_meta(job_id=str(other.id)).course == "Diritto"
    assert path.read_bytes() == original


@pytest.mark.parametrize("subject", ["Fisica", "㍿" * 26])
def test_rename_course_legacy_course_registers_stable_id(
    client: TestClient, tmp_path: Path, subject: str
) -> None:
    from sbobina.courses import course_key

    JobStore(data_dir=tmp_path).create(config=JobConfig(subject=subject))
    response = client.post(
        f"{COURSES_URL}/{course_key(subject)}/rename", json={"label": "Fisica II"}
    )
    assert response.status_code == 200
    saved = find_by_key(tmp_path / "courses", key="fisica ii")
    assert saved is not None and saved.id == response.json()["data"]["id"]


def test_rename_course_foreign_origin_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    course = get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    url = f"{COURSES_URL}/fisica/rename"
    response = client.post(
        url, json={"label": "Fisica II"}, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert find_by_key(tmp_path / "courses", key="fisica") == course
    assert client.post(url, json={"label": "Fisica II"}).status_code == 200


@pytest.mark.parametrize(
    "payload", [{}, {"label": None}, {"label": 4}, {"label": " "}, {"label": "x" * 101}]
)
def test_rename_course_invalid_label_reports_field(
    client: TestClient, tmp_path: Path, payload: dict[str, object]
) -> None:
    get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    response = client.post(f"{COURSES_URL}/fisica/rename", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.label"


def test_rename_course_existing_destination_returns_conflict(
    client: TestClient, tmp_path: Path
) -> None:
    first = get_or_create(tmp_path / "courses", key="fisica", label="Fisica")
    second = get_or_create(tmp_path / "courses", key="diritto", label="Diritto")
    document = tmp_path / "courses" / second.id / "documents" / "original.txt"
    document.parent.mkdir()
    document.write_text("Appunti", encoding="utf-8")
    response = client.post(f"{COURSES_URL}/fisica/rename", json={"label": "Diritto"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_EXISTS"
    assert find_by_key(tmp_path / "courses", key="fisica") == first
    assert find_by_key(tmp_path / "courses", key="diritto") == second
    assert document.read_text("utf-8") == "Appunti"


def test_rename_course_unknown_source_returns_not_found(client: TestClient) -> None:
    response = client.post(f"{COURSES_URL}/missing/rename", json={"label": "Fisica"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
