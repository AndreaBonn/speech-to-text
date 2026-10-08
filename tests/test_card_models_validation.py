"""Field validation and rejection paths for card_models (anchors, naive datetimes, text)."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid1, uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from test_card_models import ANCHORS, DOC_ID, GENERATION_ID, JOB_ID, NOW, STATE

from sbobina.card_models import (
    Anchor,
    Card,
    CardCreated,
    CardDeleted,
    CardDraft,
    CardEdited,
    CardSuspended,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
    ReviewEvent,
    dump_card_event,
    load_card_event,
)
from sbobina.flashcard_scheduler import Rating


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
    valid = LectureAnchor(job_id=JOB_ID, revision="r", segment_index=0, quote="q")
    assert valid.segment_index == 0
    with pytest.raises(ValueError, match="job_id"):
        LectureAnchor(job_id="", revision="r", segment_index=0, quote="q")
    with pytest.raises(ValueError, match="segment_index"):
        LectureAnchor(job_id=JOB_ID, revision="r", segment_index=-1, quote="q")
    with pytest.raises(ValueError, match="quote"):
        LectureAnchor(job_id=JOB_ID, revision="r", segment_index=0, quote=" ")


def test_document_anchor_rejects_empty_ids_negative_page_and_empty_quote() -> None:
    valid = DocumentAnchor(doc_id=DOC_ID, sha256="s", page=0, quote="q")
    assert valid.page == 0
    with pytest.raises(ValueError, match="doc_id"):
        DocumentAnchor(doc_id="", sha256="s", page=0, quote="q")
    with pytest.raises(ValueError, match="page"):
        DocumentAnchor(doc_id=DOC_ID, sha256="s", page=-1, quote="q")
    with pytest.raises(ValueError, match="quote"):
        DocumentAnchor(doc_id=DOC_ID, sha256="s", page=0, quote="")


def test_lecture_anchor_empty_revision_is_rejected() -> None:
    anchor = LectureAnchor(job_id=JOB_ID, revision="r", segment_index=0, quote="q")
    assert (anchor.job_id, anchor.revision, anchor.segment_index, anchor.quote) == (
        JOB_ID,
        "r",
        0,
        "q",
    )
    with pytest.raises(ValueError, match="revision"):
        LectureAnchor(job_id=JOB_ID, revision="", segment_index=0, quote="q")


def test_document_anchor_empty_sha256_is_rejected() -> None:
    anchor = DocumentAnchor(doc_id=DOC_ID, sha256="s", page=0, quote="q")
    assert (anchor.doc_id, anchor.sha256, anchor.page, anchor.quote) == (
        DOC_ID,
        "s",
        0,
        "q",
    )
    with pytest.raises(ValueError, match="sha256"):
        DocumentAnchor(doc_id=DOC_ID, sha256="", page=0, quote="q")


def test_generation_anchor_rejects_empty_id_and_negative_index() -> None:
    valid = GenerationAnchor(generation_id=GENERATION_ID, question_index=0)
    assert valid.question_index == 0
    with pytest.raises(ValueError):
        GenerationAnchor(generation_id="", question_index=0)
    with pytest.raises(ValueError):
        GenerationAnchor(generation_id=GENERATION_ID, question_index=-1)


@pytest.mark.parametrize(
    "build",
    [
        lambda value: LectureAnchor(
            job_id=value, revision="r", segment_index=0, quote="q"
        ),
        lambda value: DocumentAnchor(doc_id=value, sha256="s", page=0, quote="q"),
        lambda value: GenerationAnchor(generation_id=value, question_index=0),
    ],
    ids=["lecture", "document", "generation"],
)
@pytest.mark.parametrize(
    "invalid_id",
    ["../etc/passwd", "../x", "not-a-uuid", str(uuid1())],
    ids=["traversal", "traversal-short", "non-uuid", "uuid-v1"],
)
def test_anchor_ids_reject_non_uuid4_and_accept_uuid4(
    build: Callable[[str], Anchor], invalid_id: str
) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        build(invalid_id)
    identifier = str(uuid4())
    valid = build(identifier)
    match valid:
        case LectureAnchor(job_id=value):
            assert value == identifier
        case DocumentAnchor(doc_id=value):
            assert value == identifier
        case GenerationAnchor(generation_id=value):
            assert value == identifier
        case _:
            pytest.fail("Expected a supported anchor with the supplied UUID4")


def test_require_uuid4_rejects_non_canonical_form() -> None:
    non_canonical = str(uuid4()).upper()
    assert non_canonical != str(UUID(non_canonical))
    with pytest.raises(ValueError, match="UUID4"):
        GenerationAnchor(generation_id=non_canonical, question_index=0)


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
