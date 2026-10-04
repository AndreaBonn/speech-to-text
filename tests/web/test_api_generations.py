from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from generation_api_fixtures import (
    COURSES_URL,
    _make_record,
    _mc_question,
    _register_course,
    _store,
    client,
)

from sbobina.generation_models import (
    GenerationStatus,
)
from sbobina.web.generation_store import (
    generation_path,
)

__all__ = ["client"]


def test_create_generation_accepted_and_queued(
    client: TestClient, tmp_path: Path
) -> None:
    _register_course(tmp_path=tmp_path)
    response = client.post(
        f"{COURSES_URL}/fisica/generations",
        json={"format": "multiple_choice", "count": 5, "topic": "cinematica"},
    )
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["requested_count"] == 5


def test_create_generation_validation_error(client: TestClient, tmp_path: Path) -> None:
    _register_course(tmp_path=tmp_path)
    response = client.post(
        f"{COURSES_URL}/fisica/generations",
        json={"format": "multiple_choice", "count": 0},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_generation_empty_course_key_is_conflict(client: TestClient) -> None:
    response = client.post(
        f"{COURSES_URL}//generations", json={"format": "open", "count": 1}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_REQUIRED"


def test_create_generation_unregistered_course_is_not_found(client: TestClient) -> None:
    response = client.post(
        f"{COURSES_URL}/sconosciuto/generations", json={"format": "open", "count": 1}
    )
    assert response.status_code == 404


def test_create_generation_foreign_origin_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    _register_course(tmp_path=tmp_path)
    response = client.post(
        f"{COURSES_URL}/fisica/generations",
        json={"format": "open", "count": 1},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_list_generations_paginated_newest_first(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    first = _make_record(tmp_path=tmp_path, course_id=course_id)
    second = _make_record(tmp_path=tmp_path, course_id=course_id)
    generation_path(
        courses_dir=_store(tmp_path).courses_dir, course_id=course_id, gen_id=second.id
    ).touch()

    response = client.get(f"{COURSES_URL}/fisica/generations", params={"per_page": 1})
    body = response.json()

    assert response.status_code == 200
    assert body["meta"] == {
        "page": 1,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
        "unavailable_generations": [],
    }
    assert body["data"][0]["id"] == second.id
    second_page = client.get(
        f"{COURSES_URL}/fisica/generations", params={"page": 2, "per_page": 1}
    ).json()
    assert second_page["data"][0]["id"] == first.id


def test_list_generations_unregistered_course_is_empty(client: TestClient) -> None:
    response = client.get(f"{COURSES_URL}/sconosciuto/generations")
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
            "unavailable_generations": [],
        },
    }


def test_list_generations_unreadable_record_is_reported_not_fatal(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    good = _make_record(tmp_path=tmp_path, course_id=course_id)
    bad_id = str(uuid4())
    generation_path(
        courses_dir=_store(tmp_path).courses_dir, course_id=course_id, gen_id=bad_id
    ).write_text("{", encoding="utf-8")

    response = client.get(f"{COURSES_URL}/fisica/generations")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [good.id]
    assert response.json()["meta"]["total"] == 1
    assert response.json()["meta"]["unavailable_generations"] == [bad_id]


def test_get_generation_not_found(client: TestClient, tmp_path: Path) -> None:
    _register_course(tmp_path=tmp_path)
    response = client.get(f"{COURSES_URL}/fisica/generations/missing")
    assert response.status_code == 404


def test_delete_generation_busy_while_queued(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(tmp_path=tmp_path, course_id=course_id)

    response = client.delete(f"{COURSES_URL}/fisica/generations/{record.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GENERATION_BUSY"


def test_delete_generation_removes_it(client: TestClient, tmp_path: Path) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path, course_id=course_id, status=GenerationStatus.DONE
    )

    response = client.delete(f"{COURSES_URL}/fisica/generations/{record.id}")

    assert response.status_code == 204
    assert (
        client.get(f"{COURSES_URL}/fisica/generations/{record.id}").status_code == 404
    )


def test_delete_generation_foreign_origin_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path, course_id=course_id, status=GenerationStatus.DONE
    )

    response = client.delete(
        f"{COURSES_URL}/fisica/generations/{record.id}",
        headers={"Origin": "http://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_cancel_generation_queued(client: TestClient, tmp_path: Path) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(tmp_path=tmp_path, course_id=course_id)

    response = client.post(f"{COURSES_URL}/fisica/generations/{record.id}/cancel")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "interrupted"


def test_cancel_generation_not_cancellable_is_conflict(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path, course_id=course_id, status=GenerationStatus.DONE
    )

    response = client.post(f"{COURSES_URL}/fisica/generations/{record.id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"


def test_delete_generation_twice_is_not_a_server_error(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        status=GenerationStatus.DONE,
        questions=(_mc_question(correct="x"),),
    )
    url = f"{COURSES_URL}/fisica/generations/{record.id}"

    first = client.delete(url)
    second = client.delete(url)

    assert first.status_code == 204
    assert second.status_code == 404
