import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

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
JOB_ID = str(uuid4())
DOC_ID = str(uuid4())
GENERATION_ID = str(uuid4())
ANCHORS = (
    LectureAnchor(job_id=JOB_ID, revision="rev", segment_index=2, quote="testo"),
    DocumentAnchor(doc_id=DOC_ID, sha256="abc", page=3, quote="citazione"),
    GenerationAnchor(generation_id=GENERATION_ID, question_index=0),
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


def test_review_event_round_trip_preserves_state() -> None:
    event = ReviewEvent(
        card_id="id", rating=Rating.GOOD, reviewed_at=NOW, duration_ms=700, fsrs=STATE
    )
    assert load_review(content=dump_review(event=event)) == event
    with pytest.raises(FrozenInstanceError):
        setattr(event, fields(event)[0].name, 900)


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
