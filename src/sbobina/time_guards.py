"""Shared invariant: domain datetimes are always timezone-aware.

Lives in its own module (not in card_models.py or flashcard_scheduler.py)
to avoid a circular import: card_models imports FsrsState from
flashcard_scheduler, so flashcard_scheduler cannot import back from
card_models.
"""

from datetime import datetime


def require_aware(*, value: datetime, field: str) -> None:
    """Raise ValueError if `value` is a naive datetime.

    Parameters
    ----------
    value : datetime
        The datetime to check.
    field : str
        Name reported in the error message.
    """
    if value.tzinfo is None:
        raise ValueError(f"{field} deve essere timezone-aware (UTC).")
