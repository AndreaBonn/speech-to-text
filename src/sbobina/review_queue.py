from collections.abc import Sequence
from datetime import datetime

from sbobina.card_models import Card
from sbobina.time_guards import require_aware


def due_today(cards: Sequence[Card], now: datetime, new_limit: int) -> tuple[Card, ...]:
    """Return overdue cards in due order, followed by a limited set of new cards.

    Parameters
    ----------
    cards : Sequence[Card]
        Current card views; suspended cards are excluded.
    now : datetime
        Timezone-aware instant, inclusive of cards due exactly now.
    new_limit : int
        Nonnegative queue limit for cards that have never been reviewed.
    """
    require_aware(value=now, field="now")
    if new_limit < 0:
        raise ValueError("Il limite delle nuove carte deve essere non negativo")
    overdue = sorted(
        (
            (card.fsrs.due, index, card)
            for index, card in enumerate(cards)
            if not card.suspended and card.fsrs is not None and card.fsrs.due <= now
        ),
        key=lambda item: (item[0], item[1]),
    )
    fresh = tuple(card for card in cards if not card.suspended and card.fsrs is None)
    return tuple(card for _, _, card in overdue) + fresh[:new_limit]


def next_due(cards: Sequence[Card], now: datetime) -> datetime | None:
    """Return when the next scheduled card falls due after ``now``.

    Parameters
    ----------
    cards : Sequence[Card]
        Current card views; suspended and never-reviewed cards are ignored.
    now : datetime
        Timezone-aware instant; cards due at or before it are already in today's queue.

    Returns
    -------
    datetime | None
        The earliest future due date, or None when no card is scheduled.
    """
    require_aware(value=now, field="now")
    upcoming = [
        card.fsrs.due
        for card in cards
        if not card.suspended and card.fsrs is not None and card.fsrs.due > now
    ]
    return min(upcoming, default=None)
