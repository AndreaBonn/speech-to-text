import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Thread
from uuid import UUID, uuid4

import pytest

from sbobina.card_models import (
    Card,
    CardDeleted,
    CardDraft,
    CardEdited,
    CardSuspended,
    GenerationAnchor,
    ReviewEvent,
)
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.web import card_store, chat_store, path_locks
from sbobina.web.errors import NotFoundError

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
COURSE = "course"
logger = logging.getLogger(__name__)
GENERATION_ID = str(uuid4())
DRAFT = CardDraft(
    front="fronte",
    back="retro",
    source="corso",
    anchor=GenerationAnchor(generation_id=GENERATION_ID, question_index=0),
    dedup_key="key",
)


def _create(root: Path, draft: CardDraft = DRAFT) -> Card:
    return card_store.create_card(
        courses_dir=root, course_id=COURSE, draft=draft, now=NOW
    )


def _review(root: Path, card: Card, now: datetime = NOW) -> ReviewEvent:
    return card_store.record_review(
        courses_dir=root,
        course_id=COURSE,
        request=card_store.ReviewRequest(
            card_id=card.id,
            rating=Rating.GOOD,
            observed_due=card.fsrs.due if card.fsrs else None,
            now=now,
        ),
        scheduler=Scheduler(enable_fuzzing=False),
    )


def _parallel(actions: list[Callable[[], None]]) -> list[Exception]:
    barrier = Barrier(parties=len(actions))
    errors: list[Exception] = []

    def run(action: Callable[[], None]) -> None:
        try:
            barrier.wait(timeout=10)
            action()
        except Exception as error:
            logger.exception("Concurrent action failed")
            errors.append(error)

    threads = [
        Thread(target=run, kwargs={"action": action}, daemon=True) for action in actions
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    return errors


def test_lock_for_shares_registry_with_chat(tmp_path: Path) -> None:
    first = path_locks.lock_for(path=tmp_path / "first")
    assert path_locks.lock_for(path=tmp_path / "first") is first
    assert chat_store._CHAT_LOCKS[tmp_path / "first"] is first
    assert path_locks.lock_for(path=tmp_path / "second") is not first


def test_create_card_new_card_persists_at_course_path(tmp_path: Path) -> None:
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == []

    card = _create(root=tmp_path)

    assert UUID(hex=card.id).version == 4
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [card]
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    assert path == tmp_path / COURSE / "cards" / "cards.jsonl"
    assert len(path.read_text().splitlines()) == 1


def test_create_card_same_key_returns_existing_card(tmp_path: Path) -> None:
    first = _create(root=tmp_path)

    duplicate = _create(root=tmp_path)

    assert duplicate == first
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    assert len(path.read_text().splitlines()) == 1


def test_create_card_same_key_in_other_course_creates_separate_card(
    tmp_path: Path,
) -> None:
    first = _create(root=tmp_path)

    other = card_store.create_card(
        courses_dir=tmp_path, course_id="other", draft=DRAFT, now=NOW
    )

    assert other.id != first.id
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [first]
    assert card_store.load_cards(courses_dir=tmp_path, course_id="other") == [other]


def test_create_card_without_key_preserves_identical_manual_cards(
    tmp_path: Path,
) -> None:
    manual = replace(DRAFT, dedup_key=None)

    first = _create(root=tmp_path, draft=manual)
    second = _create(root=tmp_path, draft=manual)

    assert first.id != second.id
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [
        first,
        second,
    ]


def test_create_card_parallel_dedup_writes_once(tmp_path: Path) -> None:
    results: list[Card] = []

    def create() -> None:
        results.append(_create(root=tmp_path))

    assert _parallel(actions=[create, create]) == []
    assert len(results) == 2
    assert results[0] == results[1]
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    assert len(path.read_text().splitlines()) == 1


def test_append_card_event_folds_edits_suspension_and_deletion(tmp_path: Path) -> None:
    card = _create(root=tmp_path)
    event = _review(root=tmp_path, card=card)
    edit = CardEdited(
        card_id=card.id, occurred_at=NOW, front="nuovo", back="modificato"
    )
    card_store.append_card_event(courses_dir=tmp_path, course_id=COURSE, event=edit)
    suspension = CardSuspended(card_id=card.id, occurred_at=NOW)
    card_store.append_card_event(
        courses_dir=tmp_path, course_id=COURSE, event=suspension
    )
    [folded] = card_store.load_cards(courses_dir=tmp_path, course_id=COURSE)
    assert folded == replace(
        card, front="nuovo", back="modificato", suspended=True, fsrs=event.fsrs
    )
    card_store.append_card_event(
        courses_dir=tmp_path,
        course_id=COURSE,
        event=replace(suspension, suspended=False),
    )
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [
        replace(folded, suspended=False)
    ]
    deletion = CardDeleted(card_id=card.id, occurred_at=NOW)
    card_store.append_card_event(courses_dir=tmp_path, course_id=COURSE, event=deletion)
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == []
    with pytest.raises(NotFoundError):
        _review(root=tmp_path, card=card)
    assert _create(root=tmp_path).id != card.id


def test_append_preserves_valid_tail_without_newline(tmp_path: Path) -> None:
    first = _create(root=tmp_path)
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    second = _create(root=tmp_path, draft=replace(DRAFT, dedup_key=None))
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [
        first,
        second,
    ]
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 2


def test_create_and_edit_invalid_text_leave_file_unchanged(tmp_path: Path) -> None:
    card = _create(root=tmp_path)
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    original = path.read_bytes()
    assert card.front == "fronte"
    with pytest.raises(ValueError):
        _create(root=tmp_path, draft=replace(DRAFT, front="", dedup_key=None))
    with pytest.raises(ValueError):
        card_store.append_card_event(
            courses_dir=tmp_path,
            course_id=COURSE,
            event=CardEdited(card_id=card.id, occurred_at=NOW, front=" ", back="b"),
        )
    assert path.read_bytes() == original
