from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import fsrs
import pytest

from sbobina.flashcard_scheduler import FsrsState, FsrsStateLabel, Rating, review

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


@pytest.mark.parametrize("ratings", [(1, 3, 3, 4), (4, 1, 2, 3)])
def test_review_fixed_sequence_matches_library(ratings: tuple[int, ...]) -> None:
    scheduler = fsrs.Scheduler(enable_fuzzing=False)
    direct = fsrs.Card(card_id=0, due=NOW)
    state: FsrsState | None = None
    times = (
        NOW,
        NOW + timedelta(minutes=1),
        NOW + timedelta(minutes=11),
        NOW + timedelta(days=5),
    )
    for value, now in zip(ratings, times, strict=True):
        rating = tuple(Rating)[value - 1]
        state = review(state=state, rating=rating, now=now, scheduler=scheduler)
        direct, log = scheduler.review_card(
            card=direct, rating=fsrs.Rating(value=value), review_datetime=now
        )
        assert state.state.value == direct.state.name.lower()
        assert state.step == direct.step
        assert state.due == direct.due
        assert state.stability == pytest.approx(direct.stability)
        assert state.difficulty == pytest.approx(direct.difficulty)
        assert state.last_review == log.review_datetime == now


@pytest.mark.parametrize(
    ("rating", "library_rating"),
    [
        (Rating.AGAIN, fsrs.Rating.Again),
        (Rating.HARD, fsrs.Rating.Hard),
        (Rating.GOOD, fsrs.Rating.Good),
        (Rating.EASY, fsrs.Rating.Easy),
    ],
)
def test_review_new_card_due_matches_rating(
    rating: Rating, library_rating: fsrs.Rating
) -> None:
    scheduler = fsrs.Scheduler(enable_fuzzing=False)
    expected, _ = scheduler.review_card(
        card=fsrs.Card(card_id=0, due=NOW), rating=library_rating, review_datetime=NOW
    )

    state = review(
        state=None,
        rating=rating,
        now=NOW,
        scheduler=scheduler,
    )

    assert state.due == expected.due
    assert state.last_review == NOW
    with pytest.raises(FrozenInstanceError):
        setattr(state, fields(state)[0].name, NOW)


def test_rating_unknown_label_is_rejected() -> None:
    assert Rating(value="Bene") is Rating.GOOD
    with pytest.raises(ValueError):
        Rating(value="Unknown")


def test_review_preserves_input_state() -> None:
    scheduler = fsrs.Scheduler(enable_fuzzing=False)
    state = review(state=None, rating=Rating.GOOD, now=NOW, scheduler=scheduler)
    updated = review(
        state=state, rating=Rating.GOOD, now=state.due, scheduler=scheduler
    )
    assert state.due == NOW + timedelta(minutes=10)
    assert state.step == 1
    assert updated.step is None
    assert updated.due > state.due


def test_fsrs_state_rejects_naive_due_and_last_review() -> None:
    aware = FsrsState(
        state=FsrsStateLabel.LEARNING, step=1, stability=1.0, difficulty=1.0, due=NOW
    )
    assert aware.due == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        FsrsState(
            state=FsrsStateLabel.LEARNING,
            step=1,
            stability=1.0,
            difficulty=1.0,
            due=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        FsrsState(
            state=FsrsStateLabel.LEARNING,
            step=1,
            stability=1.0,
            difficulty=1.0,
            due=NOW,
            last_review=NOW.replace(tzinfo=None),
        )


def test_review_naive_time_is_rejected() -> None:
    scheduler = fsrs.Scheduler(enable_fuzzing=False)
    assert (
        review(state=None, rating=Rating.GOOD, now=NOW, scheduler=scheduler).due > NOW
    )
    with pytest.raises(ValueError, match="UTC"):
        review(
            state=None,
            rating=Rating.GOOD,
            now=NOW.replace(tzinfo=None),
            scheduler=scheduler,
        )
