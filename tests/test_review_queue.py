from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sbobina.card_models import Card, GenerationAnchor
from sbobina.flashcard_scheduler import FsrsState, FsrsStateLabel
from sbobina.review_queue import due_today, next_due
from sbobina.settings import Settings

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
GENERATION_ID = str(uuid4())


def card_fixture(identifier: str = "card", due: datetime | None = None) -> Card:
    state = (
        None
        if due is None
        else FsrsState(
            state=FsrsStateLabel.REVIEW,
            step=None,
            stability=1,
            difficulty=1,
            due=due,
        )
    )
    return Card(
        id=identifier,
        front="Fronte",
        back="Retro",
        source="manual",
        anchor=GenerationAnchor(generation_id=GENERATION_ID, question_index=0),
        fsrs=state,
    )


def test_due_today_three_overdue_thirty_new_returns_twenty_three_sorted() -> None:
    overdue = [
        card_fixture(identifier=str(i), due=NOW - timedelta(hours=i)) for i in range(3)
    ]
    fresh = [card_fixture(identifier=f"new{i}") for i in range(30)]
    future = card_fixture(identifier="tomorrow", due=NOW + timedelta(days=1))
    suspended = replace(card_fixture(identifier="suspended", due=NOW), suspended=True)
    cards = [*fresh, *overdue, future, suspended, replace(fresh[0], suspended=True)]
    before = tuple(cards)
    result = due_today(cards=cards, now=NOW, new_limit=20)
    assert result == (*reversed(overdue), *fresh[:20])
    assert len(result) == 23 and tuple(cards) == before


def test_due_today_zero_new_limit_keeps_overdue_card() -> None:
    overdue = card_fixture(due=NOW)
    assert due_today(cards=[card_fixture(), overdue], now=NOW, new_limit=0) == (
        overdue,
    )


def test_due_today_empty_cards_returns_empty_queue() -> None:
    card = card_fixture()
    assert due_today(cards=[card], now=NOW, new_limit=20) == (card,)

    assert due_today(cards=[], now=NOW, new_limit=20) == ()


def test_due_today_negative_limit_raises_value_error() -> None:
    assert due_today(cards=[card_fixture()], now=NOW, new_limit=1) == (card_fixture(),)
    with pytest.raises(ValueError, match="limite"):
        due_today(cards=[], now=NOW, new_limit=-1)


def test_due_today_naive_clock_raises_value_error() -> None:
    card = card_fixture()
    assert due_today(cards=[card], now=NOW, new_limit=1) == (card,)

    with pytest.raises(ValueError, match="timezone-aware"):
        due_today(cards=[], now=NOW.replace(tzinfo=None), new_limit=1)


def test_settings_review_new_per_day_default_environment_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(name="SBOBINA_REVIEW_NEW_PER_DAY", raising=False)
    assert Settings().review_new_per_day == 20
    monkeypatch.setenv(name="SBOBINA_REVIEW_NEW_PER_DAY", value="0")
    assert Settings().review_new_per_day == 0
    with pytest.raises(ValidationError):
        Settings(review_new_per_day=-1)


def test_next_due_returns_the_earliest_future_due_card() -> None:
    """P1: with nothing due today the review page says when cards come back."""
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    cards = [
        card_fixture(identifier="later", due=now + timedelta(days=5)),
        card_fixture(identifier="sooner", due=now + timedelta(days=2)),
        card_fixture(identifier="past", due=now - timedelta(days=1)),
        replace(
            card_fixture(identifier="paused", due=now + timedelta(days=1)),
            suspended=True,
        ),
    ]

    assert next_due(cards=cards, now=now) == now + timedelta(days=2)


def test_next_due_without_scheduled_cards_is_none() -> None:
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)

    assert next_due(cards=[card_fixture(identifier="new")], now=now) is None
    assert next_due(cards=[], now=now) is None
