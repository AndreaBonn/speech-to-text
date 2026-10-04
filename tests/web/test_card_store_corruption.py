"""Truncated/invalid JSONL repair and skip-with-warning behavior (card_store)."""

import json
import logging
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from test_card_store import COURSE, DRAFT, NOW, _create, _review

from sbobina.card_models import CardCreated, GenerationAnchor, dump_card_event
from sbobina.web import card_store

OTHER_GENERATION_ID = str(uuid4())


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
        anchor=GenerationAnchor(generation_id=OTHER_GENERATION_ID, question_index=1),
    )
    raw = json.loads(dump_card_event(event=valid_event))
    raw["front"] = ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(raw) + "\n")
    with caplog.at_level(logging.WARNING):
        assert card_store.load_cards(courses_dir=tmp_path, course_id=COURSE) == [card]
    assert "Skipping" in caplog.text
