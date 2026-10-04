import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from sbobina.card_models import (
    Anchor,
    Card,
    CardCreated,
    CardDeleted,
    CardDraft,
    CardEdited,
    CardEvent,
    CardSuspended,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
    ReviewEvent,
    dump_card_event,
    dump_review,
    load_card_event,
    load_review,
)
from sbobina.flashcard_scheduler import FsrsState, FsrsStateLabel, Rating

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
ANCHORS = (
    LectureAnchor(job_id="lecture", revision="rev", segment_index=2, quote="testo"),
    DocumentAnchor(doc_id="document", sha256="abc", page=3, quote="citazione"),
    GenerationAnchor(generation_id="generation", question_index=0),
)
STATE = FsrsState(
    state=FsrsStateLabel.LEARNING,
    step=1,
    stability=2.3,
    difficulty=4.5,
    due=NOW + timedelta(minutes=10),
    last_review=NOW,
)


@pytest.mark.parametrize("anchor", ANCHORS)
def test_card_created_round_trip_preserves_anchor(anchor: Anchor) -> None:
    event = CardCreated(
        card_id="id",
        occurred_at=NOW,
        front="fronte",
        back="retro",
        source="corso",
        anchor=anchor,
        dedup_key="dedup",
    )
    content = dump_card_event(event=event)
    assert load_card_event(content=content) == event
    assert json.loads(content)["anchor"]["kind"] == anchor.kind
    assert "fsrs" not in json.loads(content)
    assert "state" not in json.loads(content)["anchor"]
    assert "due" not in content
    with pytest.raises(FrozenInstanceError):
        setattr(anchor, fields(anchor)[0].name, "unknown")


@pytest.mark.parametrize(
    "event",
    [
        CardEdited(card_id="id", occurred_at=NOW, front="nuovo", back="retro"),
        CardSuspended(card_id="id", occurred_at=NOW, suspended=True),
        CardSuspended(card_id="id", occurred_at=NOW, suspended=False),
        CardDeleted(card_id="id", occurred_at=NOW),
    ],
)
def test_card_event_round_trip_preserves_lifecycle(event: CardEvent) -> None:
    content = dump_card_event(event=event)
    assert load_card_event(content=content) == event
    assert "fsrs" not in json.loads(content)
    with pytest.raises(FrozenInstanceError):
        setattr(event, fields(event)[0].name, "other")


@pytest.mark.parametrize("target", ["anchor", "event"])
def test_load_card_event_unknown_kind_is_rejected(target: str) -> None:
    event = CardCreated(
        card_id="id",
        occurred_at=NOW,
        front="f",
        back="b",
        source="s",
        anchor=ANCHORS[0],
    )
    content = dump_card_event(event=event)
    assert load_card_event(content=content) == event
    raw = json.loads(content)
    if target == "anchor":
        raw["anchor"]["kind"] = "unknown"
    else:
        raw["kind"] = "unknown"
    with pytest.raises(PydanticValidationError):
        load_card_event(content=json.dumps(raw))


def test_review_event_round_trip_preserves_state() -> None:
    event = ReviewEvent(
        card_id="id", rating=Rating.GOOD, reviewed_at=NOW, duration_ms=700, fsrs=STATE
    )
    assert load_review(content=dump_review(event=event)) == event
    with pytest.raises(FrozenInstanceError):
        setattr(event, fields(event)[0].name, 900)


def test_review_event_due_before_review_is_rejected() -> None:
    event = ReviewEvent(
        card_id="id",
        rating=Rating.GOOD,
        reviewed_at=STATE.due,
        duration_ms=None,
        fsrs=STATE,
    )
    assert event.fsrs.due == event.reviewed_at
    with pytest.raises(ValueError, match="due"):
        replace(event, reviewed_at=STATE.due + timedelta(seconds=1))


@pytest.mark.parametrize(
    "build",
    [
        lambda front: CardDraft(
            front=front, back="retro", source="s", anchor=ANCHORS[0]
        ),
        lambda front: CardCreated(
            card_id="id",
            occurred_at=NOW,
            front=front,
            back="retro",
            source="s",
            anchor=ANCHORS[0],
        ),
        lambda front: CardEdited(
            card_id="id", occurred_at=NOW, front=front, back="retro"
        ),
    ],
    ids=["draft", "created", "edited"],
)
def test_draft_created_edited_validate_front_like_card(
    build: Callable[[str], CardDraft | CardCreated | CardEdited],
) -> None:
    valid = build("fronte valido")
    assert valid.front == "fronte valido"
    with pytest.raises(ValueError):
        build("")


def test_lecture_anchor_rejects_empty_ids_negative_index_and_empty_quote() -> None:
    valid = LectureAnchor(job_id="j", revision="r", segment_index=0, quote="q")
    assert valid.segment_index == 0
    with pytest.raises(ValueError):
        LectureAnchor(job_id="", revision="r", segment_index=0, quote="q")
    with pytest.raises(ValueError):
        LectureAnchor(job_id="j", revision="r", segment_index=-1, quote="q")
    with pytest.raises(ValueError):
        LectureAnchor(job_id="j", revision="r", segment_index=0, quote=" ")


def test_document_anchor_rejects_empty_ids_negative_page_and_empty_quote() -> None:
    valid = DocumentAnchor(doc_id="d", sha256="s", page=0, quote="q")
    assert valid.page == 0
    with pytest.raises(ValueError):
        DocumentAnchor(doc_id="", sha256="s", page=0, quote="q")
    with pytest.raises(ValueError):
        DocumentAnchor(doc_id="d", sha256="s", page=-1, quote="q")
    with pytest.raises(ValueError):
        DocumentAnchor(doc_id="d", sha256="s", page=0, quote="")


def test_generation_anchor_rejects_empty_id_and_negative_index() -> None:
    valid = GenerationAnchor(generation_id="g", question_index=0)
    assert valid.question_index == 0
    with pytest.raises(ValueError):
        GenerationAnchor(generation_id="", question_index=0)
    with pytest.raises(ValueError):
        GenerationAnchor(generation_id="g", question_index=-1)


def test_review_event_rejects_naive_reviewed_at() -> None:
    aware = ReviewEvent(
        card_id="id", rating=Rating.GOOD, reviewed_at=NOW, duration_ms=None, fsrs=STATE
    )
    assert aware.reviewed_at == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        ReviewEvent(
            card_id="id",
            rating=Rating.GOOD,
            reviewed_at=NOW.replace(tzinfo=None),
            duration_ms=None,
            fsrs=STATE,
        )


@pytest.mark.parametrize(
    "build",
    [
        lambda at: CardCreated(
            card_id="id",
            occurred_at=at,
            front="f",
            back="b",
            source="s",
            anchor=ANCHORS[0],
        ),
        lambda at: CardEdited(card_id="id", occurred_at=at, front="f", back="b"),
        lambda at: CardSuspended(card_id="id", occurred_at=at),
        lambda at: CardDeleted(card_id="id", occurred_at=at),
    ],
    ids=["created", "edited", "suspended", "deleted"],
)
def test_card_events_reject_naive_occurred_at(
    build: Callable[[datetime], CardCreated | CardEdited | CardSuspended | CardDeleted],
) -> None:
    assert build(NOW).occurred_at == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        build(NOW.replace(tzinfo=None))


def test_card_event_json_round_trip_keeps_occurred_at_aware() -> None:
    event = CardCreated(
        card_id="id",
        occurred_at=NOW,
        front="f",
        back="b",
        source="s",
        anchor=ANCHORS[0],
    )
    loaded = load_card_event(content=dump_card_event(event=event))
    assert loaded.occurred_at.tzinfo is not None
    assert loaded.occurred_at == NOW


def test_review_event_json_round_trip_keeps_datetimes_aware() -> None:
    event = ReviewEvent(
        card_id="id", rating=Rating.GOOD, reviewed_at=NOW, duration_ms=None, fsrs=STATE
    )
    loaded = load_review(content=dump_review(event=event))
    assert loaded.reviewed_at.tzinfo is not None
    assert loaded.fsrs.due.tzinfo is not None
    assert loaded.reviewed_at == NOW


@pytest.mark.parametrize("field_name", ["front", "back"])
@pytest.mark.parametrize("invalid", ["", " \n ", "x" * 2001])
def test_card_invalid_text_is_rejected(field_name: str, invalid: str) -> None:
    card = Card(
        id="id",
        front="x" * 2000,
        back="b" * 2000,
        source="s",
        anchor=ANCHORS[0],
        fsrs=None,
    )
    assert len(card.front) == len(card.back) == 2000
    with pytest.raises(ValueError):
        replace(
            card,
            front=invalid if field_name == "front" else card.front,
            back=invalid if field_name == "back" else card.back,
        )


def test_card_and_draft_are_frozen() -> None:
    draft = CardDraft(front="f", back="b", source="s", anchor=ANCHORS[0])
    card = Card(
        id="id",
        front=draft.front,
        back=draft.back,
        source=draft.source,
        anchor=draft.anchor,
        fsrs=None,
    )
    assert card.front == "f"
    assert draft.dedup_key is None
    with pytest.raises(FrozenInstanceError):
        setattr(card, fields(card)[0].name, "other")
    with pytest.raises(FrozenInstanceError):
        setattr(draft, fields(draft)[0].name, "other")
