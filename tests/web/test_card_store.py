import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Thread
from uuid import UUID

import pytest

from sbobina.card_models import (
    Card,
    CardCreated,
    CardDeleted,
    CardDraft,
    CardEdited,
    CardSuspended,
    GenerationAnchor,
    ReviewEvent,
    dump_card_event,
    load_review,
)
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.web import card_store, chat_store, path_locks
from sbobina.web.errors import ConflictError, NotFoundError

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
COURSE = "course"
logger = logging.getLogger(__name__)
DRAFT = CardDraft(
    front="fronte",
    back="retro",
    source="corso",
    anchor=GenerationAnchor(generation_id="gen", question_index=0),
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


def test_create_card_deduplicates_live_cards_and_isolates_courses(
    tmp_path: Path,
) -> None:
    assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == []
    first = _create(root=tmp_path)
    assert UUID(hex=first.id).version == 4
    assert _create(root=tmp_path) == first
    other = card_store.create_card(
        courses_dir=tmp_path, course_id="other", draft=DRAFT, now=NOW
    )
    assert other.id != first.id
    manual = replace(DRAFT, dedup_key=None)
    assert (
        _create(root=tmp_path, draft=manual).id
        != _create(root=tmp_path, draft=manual).id
    )
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    assert path == tmp_path / COURSE / "cards" / "cards.jsonl"
    assert len(path.read_text().splitlines()) == 3


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


@pytest.mark.parametrize("filename", ["cards.jsonl", "reviews.jsonl"])
@pytest.mark.parametrize("tail", [b'{"truncated":', b'\n{"quote":"\xc3'])
def test_load_cards_truncated_tail_warns_and_next_append_repairs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, filename: str, tail: bytes
) -> None:
    card = _create(root=tmp_path)
    first = _review(root=tmp_path, card=card)
    path = card_store.cards_dir(courses_dir=tmp_path, course_id=COURSE) / filename
    good = path.read_bytes()
    path.write_bytes(good + tail)
    with caplog.at_level(logging.WARNING):
        assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [
            replace(card, fsrs=first.fsrs)
        ]
    assert "Skipping unreadable" in caplog.text
    if filename == "cards.jsonl":
        _create(root=tmp_path, draft=replace(DRAFT, dedup_key=None))
    else:
        _review(root=tmp_path, card=replace(card, fsrs=first.fsrs), now=first.fsrs.due)
    assert path.read_bytes().startswith(good)
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 2


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


def test_load_cards_skips_invalid_record_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    card = _create(root=tmp_path)
    path = card_store.cards_path(courses_dir=tmp_path, course_id=COURSE)
    valid_event = CardCreated(
        card_id="bad",
        occurred_at=NOW,
        front="valido",
        back="valido",
        source="s",
        anchor=GenerationAnchor(generation_id="gen-bad", question_index=1),
    )
    raw = json.loads(dump_card_event(event=valid_event))
    raw["front"] = ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(raw) + "\n")
    with caplog.at_level(logging.WARNING):
        assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [card]
    assert "Skipping" in caplog.text


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
