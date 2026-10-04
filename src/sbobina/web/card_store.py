"""Append-only card and review logs, folded under process-local file locks."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sbobina.card_models import (
    Card,
    CardCreated,
    CardDeleted,
    CardDraft,
    CardEdited,
    CardEvent,
    CardSuspended,
    ReviewEvent,
    dump_card_event,
    dump_review,
    load_card_event,
    load_review,
)
from sbobina.flashcard_scheduler import Rating, Scheduler, review
from sbobina.time_guards import require_aware
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.path_locks import lock_for

logger = logging.getLogger("sbobina")
CARDS_DIRNAME = "cards"
CARDS_FILENAME = "cards.jsonl"
REVIEWS_FILENAME = "reviews.jsonl"


@dataclass(frozen=True, kw_only=True)
class ReviewRequest:
    """One answer to a card; observed_due is the due date the client was shown."""

    card_id: str
    rating: Rating
    observed_due: datetime | None
    now: datetime

    def __post_init__(self) -> None:
        require_aware(value=self.now, field="now")
        if self.observed_due is not None:
            require_aware(value=self.observed_due, field="observed_due")


def cards_dir(courses_dir: Path, course_id: str) -> Path:
    return courses_dir / course_id / CARDS_DIRNAME


def cards_path(courses_dir: Path, course_id: str) -> Path:
    return cards_dir(courses_dir=courses_dir, course_id=course_id) / CARDS_FILENAME


def reviews_path(courses_dir: Path, course_id: str) -> Path:
    return cards_dir(courses_dir=courses_dir, course_id=course_id) / REVIEWS_FILENAME


@contextmanager
def _locked_paths(courses_dir: Path, course_id: str) -> Iterator[tuple[Path, Path]]:
    cards = cards_path(courses_dir=courses_dir, course_id=course_id)
    reviews = reviews_path(courses_dir=courses_dir, course_id=course_id)
    # A fixed order makes cross-file checks atomic with edits and deletion too.
    with lock_for(path=cards), lock_for(path=reviews):
        yield cards, reviews


def _read_records[T](path: Path, parse: Callable[[str], T]) -> list[T]:
    if not path.exists():
        return []
    records: list[T] = []
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            records.append(parse(line.decode("utf-8")))
        except ValueError as error:
            logger.warning("Skipping unreadable record in %s: %s", path, error)
    return records


def _append_record[T](path: Path, content: str, parse: Callable[[str], T]) -> None:
    """Called under both locks; preserve good bytes and discard only a bad tail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_bytes().splitlines(keepends=True) if path.exists() else []
    while lines:
        try:
            parse(lines[-1].decode("utf-8"))
            break
        except ValueError as error:
            logger.warning("Discarding unreadable tail in %s: %s", path, error)
            lines.pop()
    with path.open("a+b") as handle:
        handle.truncate(sum(len(line) for line in lines))
        if lines and not lines[-1].endswith(b"\n"):
            handle.write(b"\n")
        handle.write(content.encode("utf-8"))


def _created_card(event: CardCreated) -> Card:
    return Card(
        id=event.card_id,
        front=event.front,
        back=event.back,
        source=event.source,
        anchor=event.anchor,
        fsrs=None,
    )


def _apply_card_event(event: CardEvent, cards: dict[str, Card]) -> None:
    if isinstance(event, CardCreated):
        cards[event.card_id] = _created_card(event=event)
    elif isinstance(event, CardDeleted):
        cards.pop(event.card_id, None)
    elif event.card_id in cards:
        card = cards[event.card_id]
        if isinstance(event, CardEdited):
            cards[event.card_id] = replace(card, front=event.front, back=event.back)
        elif isinstance(event, CardSuspended):
            cards[event.card_id] = replace(card, suspended=event.suspended)


def _fold_cards(events: list[CardEvent], reviews: list[ReviewEvent]) -> dict[str, Card]:
    cards: dict[str, Card] = {}
    for event in events:
        try:
            _apply_card_event(event=event, cards=cards)
        except ValueError as error:
            logger.warning(
                "Skipping invalid card event for %s: %s", event.card_id, error
            )
    for event_review in reviews:
        if event_review.card_id in cards:
            cards[event_review.card_id] = replace(
                cards[event_review.card_id], fsrs=event_review.fsrs
            )
    return cards


def _load_fold(cards: Path, reviews: Path) -> dict[str, Card]:
    return _fold_cards(
        events=_read_records(path=cards, parse=load_card_event),
        reviews=_read_records(path=reviews, parse=load_review),
    )


def load_cards(courses_dir: Path, course_id: str) -> list[Card]:
    with _locked_paths(courses_dir=courses_dir, course_id=course_id) as (
        cards,
        reviews,
    ):
        return list(_load_fold(cards=cards, reviews=reviews).values())


def _find_duplicate(
    events: list[CardEvent], cards: dict[str, Card], dedup_key: str | None
) -> Card | None:
    if dedup_key is None:
        return None
    for event in events:
        if (
            isinstance(event, CardCreated)
            and event.dedup_key == dedup_key
            and event.card_id in cards
        ):
            return cards[event.card_id]
    return None


def create_card(
    courses_dir: Path, course_id: str, draft: CardDraft, now: datetime
) -> Card:
    card, _ = create_card_result(
        courses_dir=courses_dir, course_id=course_id, draft=draft, now=now
    )
    return card


def create_card_result(
    courses_dir: Path, course_id: str, draft: CardDraft, now: datetime
) -> tuple[Card, bool]:
    with _locked_paths(courses_dir=courses_dir, course_id=course_id) as paths:
        cards, reviews = paths
        events = _read_records(path=cards, parse=load_card_event)
        folded = _fold_cards(
            events=events, reviews=_read_records(path=reviews, parse=load_review)
        )
        existing = _find_duplicate(
            events=events, cards=folded, dedup_key=draft.dedup_key
        )
        if existing is not None:
            return existing, False
        event = CardCreated(
            card_id=str(uuid4()),
            occurred_at=now,
            front=draft.front,
            back=draft.back,
            source=draft.source,
            anchor=draft.anchor,
            dedup_key=draft.dedup_key,
        )
        card = _created_card(event=event)
        _append_record(
            path=cards, content=dump_card_event(event=event), parse=load_card_event
        )
        return card, True


def append_card_event(
    courses_dir: Path, course_id: str, event: CardEdited | CardSuspended | CardDeleted
) -> None:
    with _locked_paths(courses_dir=courses_dir, course_id=course_id) as (
        cards,
        reviews,
    ):
        events = _read_records(path=cards, parse=load_card_event)
        history = _read_records(path=reviews, parse=load_review)
        if event.card_id not in _fold_cards(events=events, reviews=history):
            raise NotFoundError(entity="Carta", id=event.card_id)
        _append_record(
            path=cards, content=dump_card_event(event=event), parse=load_card_event
        )


def _check_observed_due(card: Card, observed_due: datetime | None) -> None:
    current_due = card.fsrs.due if card.fsrs else None
    if current_due != observed_due:
        raise ConflictError(
            message="La carta è già stata ripassata.", code="CARD_ALREADY_REVIEWED"
        )


def record_review(
    courses_dir: Path,
    course_id: str,
    request: ReviewRequest,
    scheduler: Scheduler,
) -> ReviewEvent:
    with _locked_paths(courses_dir=courses_dir, course_id=course_id) as paths:
        cards, reviews = paths
        card = _load_fold(cards=cards, reviews=reviews).get(request.card_id)
        if card is None:
            raise NotFoundError(entity="Carta", id=request.card_id)
        _check_observed_due(card=card, observed_due=request.observed_due)
        state = review(
            state=card.fsrs, rating=request.rating, now=request.now, scheduler=scheduler
        )
        event = ReviewEvent(
            card_id=request.card_id,
            rating=request.rating,
            reviewed_at=request.now,
            duration_ms=None,
            fsrs=state,
        )
        _append_record(
            path=reviews, content=dump_review(event=event), parse=load_review
        )
        return event
