from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sbobina.card_models import Card, GenerationAnchor
from sbobina.flashcard_scheduler import FsrsState, FsrsStateLabel
from sbobina.review_queue import due_today
from sbobina.settings import Settings

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


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
        anchor=GenerationAnchor(generation_id="generation", question_index=0),
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


def test_due_today_zero_limit_keeps_overdue_and_accepts_empty() -> None:
    overdue = card_fixture(due=NOW)
    assert due_today(cards=[card_fixture(), overdue], now=NOW, new_limit=0) == (
        overdue,
    )
    assert due_today(cards=[], now=NOW, new_limit=20) == ()


def test_due_today_invalid_limit_and_naive_clock_raise() -> None:
    assert due_today(cards=[card_fixture()], now=NOW, new_limit=1) == (card_fixture(),)
    with pytest.raises(ValueError, match="limite"):
        due_today(cards=[], now=NOW, new_limit=-1)
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
