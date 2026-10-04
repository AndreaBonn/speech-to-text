"""Keep library objects and enum values behind the scheduling boundary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import fsrs

from sbobina.time_guards import require_aware

Scheduler = fsrs.Scheduler


class FsrsStateLabel(StrEnum):
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class Rating(StrEnum):
    AGAIN = "Di nuovo"
    HARD = "Difficile"
    GOOD = "Bene"
    EASY = "Facile"


@dataclass(frozen=True)
class FsrsState:
    state: FsrsStateLabel
    step: int | None
    stability: float | None
    difficulty: float | None
    due: datetime
    # FSRS needs elapsed time, which cannot be recovered from the next due date.
    last_review: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(value=self.due, field="due")
        if self.last_review is not None:
            require_aware(value=self.last_review, field="last_review")


_RATINGS = {
    Rating.AGAIN: fsrs.Rating.Again,
    Rating.HARD: fsrs.Rating.Hard,
    Rating.GOOD: fsrs.Rating.Good,
    Rating.EASY: fsrs.Rating.Easy,
}
_STATES = {
    FsrsStateLabel.LEARNING: fsrs.State.Learning,
    FsrsStateLabel.REVIEW: fsrs.State.Review,
    FsrsStateLabel.RELEARNING: fsrs.State.Relearning,
}
_STATE_LABELS = {value: key for key, value in _STATES.items()}


def review(
    state: FsrsState | None, rating: Rating, now: datetime, scheduler: Scheduler
) -> FsrsState:
    card = fsrs.Card(card_id=0, due=now)
    if state is not None:
        card = fsrs.Card(
            card_id=0,
            state=_STATES[state.state],
            step=state.step,
            stability=state.stability,
            difficulty=state.difficulty,
            due=state.due,
            last_review=state.last_review,
        )
    updated, _ = scheduler.review_card(
        card=card, rating=_RATINGS[Rating(value=rating)], review_datetime=now
    )
    return FsrsState(
        state=_STATE_LABELS[updated.state],
        step=updated.step,
        stability=updated.stability,
        difficulty=updated.difficulty,
        due=updated.due,
        last_review=updated.last_review,
    )
