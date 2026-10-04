"""GET /courses/{key}/review/today: ordering, pagination and suspension (card_store)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_review_queue import NOW

from sbobina.card_models import Card, CardDraft, CardSuspended, GenerationAnchor
from sbobina.course_registry import get_or_create
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.card_store import (
    ReviewRequest,
    append_card_event,
    create_card,
    record_review,
)
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
TODAY_URL = "/api/v1/courses/diritto/review/today"
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


def _fixed_clock(client: TestClient) -> None:
    from sbobina.web.course_dependencies import review_clock, review_scheduler

    app = cast(FastAPI, client.app)
    app.dependency_overrides[review_clock] = lambda: NOW
    app.dependency_overrides[review_scheduler] = lambda: Scheduler(enable_fuzzing=False)


def test_today_queue_limit_pagination_and_removed_anchor(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    course_id = _course(store=store)
    for _ in range(30):
        _card(store=store, course_id=course_id)
    response = client.get(url=TODAY_URL)
    assert response.status_code == 200 and len(response.json()["data"]) == 20
    assert response.json()["data"][0]["anchor_resolution"]["status"] == "source_removed"
    assert response.json()["meta"] == {
        "page": 1,
        "per_page": 20,
        "total": 20,
        "total_pages": 1,
    }
    page = client.get(url=TODAY_URL, params={"page": 2, "per_page": 3}).json()
    assert page["data"] == response.json()["data"][3:6]
    assert page["meta"] == {"page": 2, "per_page": 3, "total": 20, "total_pages": 7}
    cast(FastAPI, client.app).state.settings.review_new_per_day = 0
    assert client.get(url=TODAY_URL).json()["data"] == []


def test_today_overdue_before_new_excludes_future_and_suspended(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    course_id = _course(store=store)
    cards = [_card(store=store, course_id=course_id) for _ in range(5)]
    for index, offset in enumerate((0, -2, -1)):
        record_review(
            courses_dir=store.courses_dir,
            course_id=course_id,
            request=ReviewRequest(
                card_id=cards[index].id,
                rating=Rating.GOOD,
                observed_due=None,
                now=NOW + timedelta(days=offset),
            ),
            scheduler=Scheduler(enable_fuzzing=False),
        )
    append_card_event(
        courses_dir=store.courses_dir,
        course_id=course_id,
        event=CardSuspended(card_id=cards[3].id, occurred_at=NOW),
    )
    payload = client.get(url=TODAY_URL).json()["data"]
    assert [card["id"] for card in payload] == [cards[1].id, cards[2].id, cards[4].id]
