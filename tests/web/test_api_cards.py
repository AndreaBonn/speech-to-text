import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from starlette.requests import Request
from test_review_queue import NOW

from sbobina.card_models import (
    Anchor,
    CardDeleted,
    CardEdited,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
)
from sbobina.course_registry import get_or_create
from sbobina.flashcard_scheduler import Scheduler
from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web import api_cards, card_store
from sbobina.web.app import create_app
from sbobina.web.card_store import cards_path
from sbobina.web.course_dependencies import ReviewServices
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore
from sbobina.web.responses import app_error_handler

BASE_URL = "http://127.0.0.1:8765"
CARDS_URL = "/api/v1/courses/diritto/cards"
QUOTE = "Il diritto regola la società"
GONE_GENERATION_ID = str(uuid4())
GONE_DOC_ID = str(uuid4())
GENERATION = GenerationAnchor(generation_id=GONE_GENERATION_ID, question_index=0)


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


def _body(anchor: Anchor = GENERATION) -> dict[str, Any]:
    return {
        "front": "Domanda",
        "back": "Risposta",
        "anchor": jsonable_encoder(obj=anchor),
    }


def test_edit_card_deleted_after_append_returns_not_found(
    store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    course = get_or_create(
        courses_dir=store.courses_dir, key="diritto", label="Diritto"
    )
    services = ReviewServices(
        store=store, settings=Settings(), now=NOW, scheduler=Scheduler()
    )
    draft = api_cards.CreateCardBody(front="Question", back="Answer", anchor=GENERATION)
    first = api_cards.add_card(body=draft, course=course, services=services)["data"]
    kept = api_cards.add_card(body=draft, course=course, services=services)["data"]
    body = api_cards.CardTextBody(front="Edited question", back="Edited answer")
    edited = api_cards.edit_card(
        card_id=first["id"], body=body, course=course, services=services
    )
    assert edited["data"]["front"] == "Edited question"

    def append_then_delete(
        *, courses_dir: Path, course_id: str, event: CardEdited
    ) -> None:
        card_store.append_card_event(
            courses_dir=courses_dir, course_id=course_id, event=event
        )
        # Schedule a real deletion in the unlocked gap before the route reloads cards.
        card_store.append_card_event(
            courses_dir=courses_dir,
            course_id=course_id,
            event=CardDeleted(card_id=event.card_id, occurred_at=NOW),
        )

    monkeypatch.setattr(api_cards, "append_card_event", append_then_delete)
    with pytest.raises(NotFoundError) as caught:
        api_cards.edit_card(
            card_id=first["id"], body=body, course=course, services=services
        )
    response = asyncio.run(
        app_error_handler(request=Request(scope={"type": "http"}), exc=caught.value)
    )

    assert response.status_code == 404
    assert json.loads(bytes(response.body))["error"]["code"] == "NOT_FOUND"
    assert [
        card.id
        for card in card_store.load_cards(
            courses_dir=store.courses_dir, course_id=course.id
        )
    ] == [kept["id"]]


def _transcript(store: JobStore, job_id: str, texts: list[str]) -> None:
    save_transcript(
        transcript=make_transcript(
            segments=[
                make_segment(words=[make_word(text=text, start=float(index))])
                for index, text in enumerate(texts)
            ]
        ),
        path=store.jobs_dir / job_id / "audio.json",
    )


def _lecture(store: JobStore) -> LectureAnchor:
    job_id = str(store.create(config=JobConfig(subject="Fisica")).id)
    store.write_meta(job_id=job_id, meta=LectureMeta(course="Diritto"))
    _transcript(store=store, job_id=job_id, texts=[QUOTE])
    revision = lecture_revision(store=store, job_id=job_id)
    assert revision is not None
    return LectureAnchor(job_id=job_id, revision=revision, segment_index=0, quote=QUOTE)


@pytest.mark.parametrize("quote", [QUOTE, "short"])
def test_create_card_current_revision_accepts_without_matching(
    client: TestClient, store: JobStore, quote: str
) -> None:
    _course(store=store)
    anchor = replace(_lecture(store=store), quote=quote)
    response = client.post(url=CARDS_URL, json=_body(anchor=anchor))
    assert response.status_code == 201
    card = response.json()["data"]
    assert card["anchor_resolution"]["status"] == "ok"
    assert card["source"] == "manual"
    assert card["anchor"] == jsonable_encoder(obj=anchor)


@pytest.mark.parametrize("texts", [["Introduzione", QUOTE], [QUOTE, "Appendice"]])
def test_create_card_old_revision_relocates_preserving_anchor(
    client: TestClient, store: JobStore, texts: list[str]
) -> None:
    _course(store=store)
    anchor = _lecture(store=store)
    _transcript(store=store, job_id=anchor.job_id, texts=texts)
    response = client.post(url=CARDS_URL, json=_body(anchor=anchor))
    assert response.status_code == 201
    assert response.json()["data"]["anchor_resolution"]["status"] == "moved"
    assert response.json()["data"]["anchor"] == jsonable_encoder(obj=anchor)
    assert client.get(url=CARDS_URL).json()["data"] == [response.json()["data"]]


@pytest.mark.parametrize("source", ["changed", "removed", "unreadable", "invalid_utf8"])
def test_create_card_missing_quote_conflicts_without_creating(
    client: TestClient, store: JobStore, source: str
) -> None:
    _course(store=store)
    anchor = _lecture(store=store)
    assert client.post(url=CARDS_URL, json=_body(anchor=anchor)).status_code == 201
    path = store.jobs_dir / anchor.job_id / "audio.json"
    if source == "removed":
        path.unlink()
    elif source == "invalid_utf8":
        path.write_bytes(data=b"\xff")
    elif source == "unreadable":
        path.write_text(data="invalid json", encoding="utf-8")
    else:
        _transcript(store=store, job_id=anchor.job_id, texts=["Un testo diverso"])
    response = client.post(url=CARDS_URL, json=_body(anchor=anchor))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_CHANGED"
    assert len(client.get(url=CARDS_URL).json()["data"]) == 1


def test_create_card_other_course_conflicts_before_freshness(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    anchor = _lecture(store=store)
    assert client.post(url=CARDS_URL, json=_body(anchor=anchor)).status_code == 201
    store.write_meta(job_id=anchor.job_id, meta=LectureMeta(course="Fisica"))
    (store.jobs_dir / anchor.job_id / "audio.json").unlink()
    response = client.post(url=CARDS_URL, json=_body(anchor=anchor))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LECTURE_NOT_IN_COURSE"


def test_create_card_missing_lecture_returns_not_found(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    anchor = _lecture(store=store)
    assert client.post(url=CARDS_URL, json=_body(anchor=anchor)).status_code == 201
    response = client.post(
        url=CARDS_URL, json=_body(anchor=replace(anchor, job_id=str(uuid4())))
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "anchor",
    [
        GENERATION,
        DocumentAnchor(doc_id=GONE_DOC_ID, sha256="old", page=0, quote=QUOTE),
    ],
)
def test_create_card_other_anchors_are_accepted(
    client: TestClient, store: JobStore, anchor: Anchor
) -> None:
    _course(store=store)

    response = client.post(url=CARDS_URL, json=_body(anchor=anchor))

    assert response.status_code == 201
    assert response.json()["data"]["anchor"] == jsonable_encoder(obj=anchor)


@pytest.mark.parametrize(
    "anchor",
    [GENERATION, DocumentAnchor(doc_id=GONE_DOC_ID, sha256="old", page=0, quote=QUOTE)],
)
def test_create_card_duplicate_gets_distinct_id(
    client: TestClient, store: JobStore, anchor: Anchor
) -> None:
    _course(store=store)
    first = client.post(url=CARDS_URL, json=_body(anchor=anchor))
    assert first.status_code == 201

    second = client.post(url=CARDS_URL, json=_body(anchor=anchor))

    assert second.status_code == 201
    assert len({first.json()["data"]["id"], second.json()["data"]["id"]}) == 2


def test_create_card_persists_review_clock_timestamp(
    client: TestClient, store: JobStore
) -> None:
    course_id = _course(store=store)

    response = client.post(url=CARDS_URL, json=_body())

    assert response.status_code == 201
    path = cards_path(courses_dir=store.courses_dir, course_id=course_id)
    assert NOW.isoformat().replace("+00:00", "Z") in path.read_text(encoding="utf-8")


def test_create_card_path_traversal_doc_id_returns_422_without_creating(
    client: TestClient, store: JobStore
) -> None:
    course_id = _course(store=store)
    body = _body()
    body["anchor"] = {
        "kind": "document",
        "doc_id": "../x",
        "sha256": "old",
        "page": 0,
        "quote": QUOTE,
    }
    response = client.post(url=CARDS_URL, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.anchor.document"
    assert cards_path(courses_dir=store.courses_dir, course_id=course_id).exists() is (
        False
    )
    assert client.get(url=CARDS_URL).json()["data"] == []


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("invalid", [("front", ""), ("back", "x" * 2001)])
def test_card_text_invalid_returns_field_error(
    client: TestClient, store: JobStore, method: str, invalid: tuple[str, str]
) -> None:
    _course(store=store)
    field, value = invalid
    body = _body()
    url = CARDS_URL
    if method == "PATCH":
        card = client.post(url=url, json=body).json()["data"]
        url = f"{url}/{card['id']}"
    response = client.request(method=method, url=url, json={**body, field: value})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == f"body.{field}"
    assert client.request(method=method, url=url, json=body).status_code in (200, 201)


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_cards_unknown_course_returns_not_found(
    client: TestClient, store: JobStore, method: str
) -> None:
    assert client.request(method=method, url=CARDS_URL, json=_body()).status_code == 404
    _course(store=store)
    assert client.request(method=method, url=CARDS_URL, json=_body()).status_code in (
        200,
        201,
    )


def test_edit_card_replaces_text_preserving_review_state(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    card = client.post(url=CARDS_URL, json=_body()).json()["data"]
    url = f"{CARDS_URL}/{card['id']}"
    review = client.post(url=f"{url}/review", json={"rating": 3, "observed_due": None})
    assert review.status_code == 200
    text = {"front": "Nuova domanda", "back": "Nuova risposta"}
    response = client.patch(url=url, json=text)
    assert response.status_code == 200
    assert response.json()["data"] == {
        **card,
        **text,
        "fsrs": review.json()["data"]["fsrs"],
    }
    assert client.get(url=CARDS_URL).json()["data"] == [response.json()["data"]]


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_card_unknown_id_returns_not_found(
    client: TestClient, store: JobStore, method: str
) -> None:
    _course(store=store)
    card = client.post(url=CARDS_URL, json=_body()).json()["data"]
    response = client.request(method=method, url=f"{CARDS_URL}/missing", json=_body())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert client.request(
        method=method, url=f"{CARDS_URL}/{card['id']}", json=_body()
    ).status_code in (200, 204)


def test_list_cards_pagination_preserves_insertion_order(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    cards = [client.post(url=CARDS_URL, json=_body()).json()["data"] for _ in range(5)]
    response = client.get(url=CARDS_URL)
    assert response.status_code == 200
    assert response.json() == {
        "data": cards,
        "meta": {"page": 1, "per_page": 20, "total": 5, "total_pages": 1},
    }
    page = client.get(url=CARDS_URL, params={"page": 2, "per_page": 2}).json()
    assert page == {
        "data": cards[2:4],
        "meta": {"page": 2, "per_page": 2, "total": 5, "total_pages": 3},
    }


def test_delete_card_returns_empty_body_and_removes_from_list(
    client: TestClient, store: JobStore
) -> None:
    _course(store=store)
    card = client.post(url=CARDS_URL, json=_body()).json()["data"]
    assert client.get(url=CARDS_URL).json()["data"] == [card]
    response = client.delete(url=f"{CARDS_URL}/{card['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(url=CARDS_URL).json()["data"] == []
