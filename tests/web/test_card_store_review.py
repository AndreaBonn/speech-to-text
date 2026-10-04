"""record_review concurrency, conflicts and request validation (card_store)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_card_store import COURSE, DRAFT, NOW, _create, _parallel, _review

from sbobina.card_models import Card, load_review
from sbobina.flashcard_scheduler import Rating
from sbobina.web import card_store
from sbobina.web.errors import ConflictError, NotFoundError


@pytest.mark.parametrize("parallel", [False, True])
def test_record_review_same_observed_due_conflicts(
    tmp_path: Path, parallel: bool
) -> None:
    card = _create(root=tmp_path)
    first = _review(root=tmp_path, card=card)
    observed = replace(card, fsrs=first.fsrs)

    def review() -> None:
        _review(root=tmp_path, card=observed, now=first.fsrs.due)

    if parallel:
        errors = _parallel(actions=[review, review])
        assert len(errors) == 1
        error = errors[0]
    else:
        review()
        with pytest.raises(ConflictError) as caught:
            review()
        error = caught.value
    assert isinstance(error, ConflictError)
    assert error.code == "CARD_ALREADY_REVIEWED"
    path = card_store.reviews_path(courses_dir=tmp_path, course_id=COURSE)
    assert len(path.read_text().splitlines()) == 2


def test_record_review_parallel_new_card_writes_once(tmp_path: Path) -> None:
    card = _create(root=tmp_path)

    def review() -> None:
        _review(root=tmp_path, card=card)

    errors = _parallel(actions=[review, review])
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    assert errors[0].code == "CARD_ALREADY_REVIEWED"
    path = card_store.reviews_path(courses_dir=tmp_path, course_id=COURSE)
    assert len(path.read_text().splitlines()) == 1


def test_record_review_two_threads_keep_all_hundred_rows(tmp_path: Path) -> None:
    cards = [
        _create(root=tmp_path, draft=replace(DRAFT, dedup_key=None)) for _ in range(2)
    ]

    def review_fifty(card: Card) -> None:
        for index in range(50):
            event = _review(
                root=tmp_path, card=card, now=NOW + timedelta(minutes=index)
            )
            card = replace(card, fsrs=event.fsrs)

    actions: list[Callable[[], None]] = [
        lambda: review_fifty(card=cards[0]),
        lambda: review_fifty(card=cards[1]),
    ]
    assert _parallel(actions=actions) == []
    path = card_store.reviews_path(courses_dir=tmp_path, course_id=COURSE)
    rows = [load_review(content=line) for line in path.read_text().splitlines()]
    assert len(rows) == 100
    for card in cards:
        assert sum(row.card_id == card.id for row in rows) == 50
    folded = card_store.load_cards(courses_dir=tmp_path, course_id=COURSE)
    assert {card.id: card.fsrs for card in folded} == {
        row.card_id: row.fsrs for row in rows
    }


def test_record_review_unknown_card_is_not_found(tmp_path: Path) -> None:
    card = _create(root=tmp_path)
    assert _review(root=tmp_path, card=card).card_id == card.id
    with pytest.raises(NotFoundError):
        _review(root=tmp_path, card=replace(card, id="missing"))


def test_review_request_rejects_naive_now_and_observed_due() -> None:
    aware = card_store.ReviewRequest(
        card_id="id", rating=Rating.GOOD, observed_due=None, now=NOW
    )
    assert aware.now == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        card_store.ReviewRequest(
            card_id="id",
            rating=Rating.GOOD,
            observed_due=None,
            now=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        card_store.ReviewRequest(
            card_id="id",
            rating=Rating.GOOD,
            observed_due=NOW.replace(tzinfo=None),
            now=NOW,
        )
