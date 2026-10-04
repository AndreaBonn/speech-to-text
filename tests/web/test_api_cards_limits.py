"""Quote/body size limits (S1, S2) and cross-course scoping (C5) for /cards."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_review_queue import NOW

from sbobina.card_models import GenerationAnchor
from sbobina.course_registry import find_by_key, get_or_create
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.card_store import cards_path
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
CARDS_URL = "/api/v1/courses/diritto/cards"
OTHER_CARDS_URL = "/api/v1/courses/fisica/cards"
GONE_GENERATION_ID = str(uuid4())
GONE_DOC_ID = str(uuid4())


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from sbobina.web.course_dependencies import review_clock

    app = create_app(settings=Settings(), data_dir=tmp_path)
    app.dependency_overrides[review_clock] = lambda: NOW
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def _course(store: JobStore) -> str:
    return get_or_create(
        courses_dir=store.courses_dir, key="diritto", label="Diritto"
    ).id


def _body() -> dict[str, Any]:
    anchor = GenerationAnchor(generation_id=GONE_GENERATION_ID, question_index=0)
    return {
        "front": "Domanda",
        "back": "Risposta",
        "anchor": {
            "kind": anchor.kind,
            "generation_id": anchor.generation_id,
            "question_index": anchor.question_index,
        },
    }


def test_create_card_quote_over_max_chars_returns_422_without_creating(
    client: TestClient, store: JobStore
) -> None:
    course_id = _course(store=store)
    body = _body()
    body["anchor"] = {
        "kind": "document",
        "doc_id": GONE_DOC_ID,
        "sha256": "old",
        "page": 0,
        "quote": "x" * 2001,
    }
    response = client.post(url=CARDS_URL, json=body)
    assert response.status_code == 422
    assert cards_path(courses_dir=store.courses_dir, course_id=course_id).exists() is (
        False
    )
    body["anchor"]["quote"] = "x" * 2000
    assert client.post(url=CARDS_URL, json=body).status_code == 201


def test_create_card_oversized_body_returns_413_without_creating(
    client: TestClient, store: JobStore
) -> None:
    course_id = _course(store=store)
    oversized = {**_body(), "front": "x" * (65 * 1024)}
    response = client.post(url=CARDS_URL, json=oversized)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert cards_path(courses_dir=store.courses_dir, course_id=course_id).exists() is (
        False
    )
    assert client.post(url=CARDS_URL, json=_body()).status_code == 201


def test_edit_card_oversized_body_returns_413_without_writing(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    card = client.post(url=CARDS_URL, json=_body()).json()["data"]
    url = f"{CARDS_URL}/{card['id']}"
    oversized = {"front": "x" * (65 * 1024), "back": "Risposta"}
    response = client.patch(url=url, json=oversized)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    text = {"front": "Nuova domanda", "back": "Nuova risposta"}
    assert client.patch(url=url, json=text).status_code == 200


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_edit_and_delete_other_course_card_returns_404_without_writing(
    client: TestClient, store: JobStore, method: str
) -> None:
    _course(store=store)
    get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    other_card = client.post(url=OTHER_CARDS_URL, json=_body()).json()["data"]
    other_course = find_by_key(courses_dir=store.courses_dir, key="fisica")
    assert other_course is not None
    other_path = cards_path(courses_dir=store.courses_dir, course_id=other_course.id)
    before = other_path.read_bytes()
    response = client.request(
        method=method, url=f"{CARDS_URL}/{other_card['id']}", json=_body()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert other_path.read_bytes() == before
