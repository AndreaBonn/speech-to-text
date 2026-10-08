from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_review_queue import NOW

from sbobina.card_models import Card, CardDraft, GenerationAnchor
from sbobina.course_registry import get_or_create
from sbobina.flashcard_scheduler import Scheduler
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.card_store import create_card, reviews_path
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
TODAY_URL = "/api/v1/courses/diritto/review/today"
SUMMARY_URL = "/api/v1/review/summary"
GONE_GENERATION_ID = str(uuid4())


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def _course(store: JobStore, key: str = "diritto") -> str:
    return get_or_create(courses_dir=store.courses_dir, key=key, label=key.title()).id


def _card(store: JobStore, course_id: str) -> Card:
    return create_card(
        courses_dir=store.courses_dir,
        course_id=course_id,
        now=NOW,
        draft=CardDraft(
            front="Fronte",
            back="Retro",
            source="manual",
            anchor=GenerationAnchor(generation_id=GONE_GENERATION_ID, question_index=0),
        ),
    )


def _review_url(card_id: str) -> str:
    return f"/api/v1/courses/diritto/cards/{card_id}/review"


def _fixed_clock(client: TestClient) -> None:
    from sbobina.web.course_dependencies import review_clock, review_scheduler

    app = cast(FastAPI, client.app)
    app.dependency_overrides[review_clock] = lambda: NOW
    app.dependency_overrides[review_scheduler] = lambda: Scheduler(enable_fuzzing=False)


@pytest.mark.parametrize(
    "rating", [1, 2, 3, 4, "Di nuovo", "Difficile", "Bene", "Facile"]
)
def test_review_valid_rating_updates_due_and_duplicate_conflicts(
    client: TestClient, store: JobStore, rating: int | str
) -> None:
    _fixed_clock(client=client)
    course_id = _course(store=store)
    card = _card(store=store, course_id=course_id)
    body = {"rating": rating, "observed_due": None}
    response = client.post(url=_review_url(card_id=card.id), json=body)
    assert response.status_code == 200
    assert response.json()["data"]["fsrs"]["due"] > NOW.isoformat().replace(
        "+00:00", "Z"
    )
    repeated = client.post(url=_review_url(card_id=card.id), json=body)
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "CARD_ALREADY_REVIEWED"
    path = reviews_path(courses_dir=store.courses_dir, course_id=course_id)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("rating", [7, 0, -1, "7", "bene", "", True, 1.5])
def test_review_invalid_rating_returns_field_error(
    client: TestClient, store: JobStore, rating: object
) -> None:
    _fixed_clock(client=client)
    card = _card(store=store, course_id=_course(store=store))
    response = client.post(
        url=_review_url(card_id=card.id), json={"rating": rating, "observed_due": None}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.rating"
    assert (
        client.post(
            url=_review_url(card_id=card.id),
            json={"rating": "Bene", "observed_due": None},
        ).status_code
        == 200
    )


def test_review_naive_observed_due_returns_field_error(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    card = _card(store=store, course_id=_course(store=store))
    response = client.post(
        url=_review_url(card_id=card.id),
        json={"rating": "Bene", "observed_due": "2026-10-04T12:00:00"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.observed_due"
    assert (
        client.post(
            url=_review_url(card_id=card.id),
            json={"rating": "Bene", "observed_due": None},
        ).status_code
        == 200
    )


def test_today_unknown_course_returns_not_found(
    client: TestClient,
) -> None:
    response = client.get(url=TODAY_URL)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def _two_courses(store: JobStore) -> None:
    for key, count in (("diritto", 2), ("fisica", 1)):
        course_id = _course(store=store, key=key)
        for _ in range(count):
            _card(store=store, course_id=course_id)


def test_summary_registered_courses_returns_due_counts(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    _two_courses(store=store)

    response = client.get(url=SUMMARY_URL)

    assert response.status_code == 200
    assert response.json()["meta"] == {
        "page": 1,
        "per_page": 20,
        "total": 2,
        "total_pages": 1,
    }
    assert sorted(response.json()["data"], key=lambda item: item["course_key"]) == [
        {"course_key": "diritto", "label": "Diritto", "due": 2},
        {"course_key": "fisica", "label": "Fisica", "due": 1},
    ]


def test_summary_second_page_returns_second_course(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    _two_courses(store=store)

    response = client.get(url=SUMMARY_URL, params={"page": 2, "per_page": 1})

    assert response.status_code == 200
    assert response.json() == {
        "data": [{"course_key": "fisica", "label": "Fisica", "due": 1}],
        "meta": {"page": 2, "per_page": 1, "total": 2, "total_pages": 2},
    }


def test_today_registered_course_returns_its_due_cards(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    course_id = _course(store=store)
    cards = [_card(store=store, course_id=course_id) for _ in range(2)]
    _card(store=store, course_id=_course(store=store, key="fisica"))

    response = client.get(url=TODAY_URL)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [
        card.id for card in cards
    ]
