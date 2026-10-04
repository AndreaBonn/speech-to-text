from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_concept_cards import study_fixture
from test_review_queue import NOW

from sbobina.card_models import (
    Card,
    CardDraft,
    CardSuspended,
    GenerationAnchor,
    LectureAnchor,
)
from sbobina.course_registry import find_by_key, get_or_create
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.study_render import STUDY_ADAPTER
from sbobina.web.app import create_app
from sbobina.web.card_store import (
    ReviewRequest,
    append_card_event,
    create_card,
    load_cards,
    record_review,
    reviews_path,
)
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
TODAY_URL = "/api/v1/courses/diritto/review/today"
SUMMARY_URL = "/api/v1/review/summary"


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def _material(store: JobStore, subject: str | None = "Diritto") -> str:
    job_id = str(store.create(config=JobConfig(subject=subject)).id)
    result = study_fixture()
    chapter = result.chapters[0]
    concepts = tuple(
        replace(item, citations=item.citations[:1]) for item in chapter.concepts
    )
    result = replace(result, chapters=(replace(chapter, concepts=concepts),))
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[make_word(text=item.citations[0].quote, start=float(i))]
            )
            for i, item in enumerate(result.chapters[0].concepts)
        ]
    )
    directory = store.jobs_dir / job_id
    save_transcript(transcript=transcript, path=directory / "audio.json")
    (directory / "audio.studio.json").write_text(
        data=STUDY_ADAPTER.dump_json(result).decode("utf-8"), encoding="utf-8"
    )
    return job_id


def _concept_url(job_id: str) -> str:
    return f"/api/v1/jobs/{job_id}/cards/from-concepts"


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
            anchor=GenerationAnchor(generation_id="gone", question_index=0),
        ),
    )


def _review_url(card_id: str) -> str:
    return f"/api/v1/courses/diritto/cards/{card_id}/review"


def _fixed_clock(client: TestClient) -> None:
    from sbobina.web.api_review import review_clock, review_scheduler

    app = cast(FastAPI, client.app)
    app.dependency_overrides[review_clock] = lambda: NOW
    app.dependency_overrides[review_scheduler] = lambda: Scheduler(enable_fuzzing=False)


def test_from_concepts_twelve_then_zero_with_effective_course(
    client: TestClient, store: JobStore
) -> None:
    job_id = _material(store=store, subject="Fisica")
    store.write_meta(job_id=job_id, meta=LectureMeta(course="Diritto"))
    response = client.post(url=_concept_url(job_id=job_id))
    assert response.status_code == 201 and response.json() == {"data": {"created": 12}}
    assert client.post(url=_concept_url(job_id=job_id)).json() == {
        "data": {"created": 0}
    }
    course = find_by_key(courses_dir=store.courses_dir, key="diritto")
    assert course is not None
    cards = load_cards(courses_dir=store.courses_dir, course_id=course.id)
    assert len(cards) == 12
    assert cards[0].front == "concetto0" and cards[0].back == "Spiegazione 0"
    assert isinstance(cards[0].anchor, LectureAnchor)
    assert cards[0].anchor.revision == lecture_revision(store=store, job_id=job_id)


def test_from_concepts_missing_study_and_uncategorized_errors(
    client: TestClient, store: JobStore
) -> None:
    job_id = _material(store=store, subject=None)
    response = client.post(url=_concept_url(job_id=job_id))
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "COURSE_REQUIRED"
    )
    store.write_meta(job_id=job_id, meta=LectureMeta(course="Diritto"))
    assert client.post(url=_concept_url(job_id=job_id)).status_code == 201
    (store.jobs_dir / job_id / "audio.studio.json").unlink()
    response = client.post(url=_concept_url(job_id=job_id))
    assert (
        response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
    )


def test_from_concepts_concurrent_import_counts_only_own_creations(
    client: TestClient, store: JobStore
) -> None:
    url = _concept_url(job_id=_material(store=store))
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(url=url), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert sorted(response.json()["data"]["created"] for response in responses) == [
        0,
        12,
    ]


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


def test_summary_two_registered_courses_and_unknown_course(
    client: TestClient, store: JobStore
) -> None:
    _fixed_clock(client=client)
    assert client.get(url=TODAY_URL).status_code == 404
    for key, count in (("diritto", 2), ("fisica", 1)):
        course_id = _course(store=store, key=key)
        for _ in range(count):
            _card(store=store, course_id=course_id)
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
    second = client.get(url=SUMMARY_URL, params={"page": 2, "per_page": 1}).json()
    assert [item["course_key"] for item in second["data"]] == ["fisica"]
    assert second["meta"]["total_pages"] == 2
    assert len(client.get(url=TODAY_URL).json()["data"]) == 2
