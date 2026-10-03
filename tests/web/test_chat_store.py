import logging
from pathlib import Path

import pytest

from sbobina.chat_pipeline import ChatAnswer, ChatOutcome, ChatSentence
from sbobina.web import chat_store
from sbobina.web.chat_records import AnswerTo, ChatAnswerRecord
from sbobina.web.chat_store import (
    TITLE_MAX_CHARS,
    append_answer,
    append_question,
    chat_path,
    create_chat,
    delete_chat,
    list_chats,
    load_records,
)
from sbobina.web.chat_turn import history_turns
from sbobina.web.errors import NotFoundError

COURSE = "corso"


def _answer(text: str) -> ChatAnswer:
    return ChatAnswer(
        outcome=ChatOutcome.DONE, sentences=(ChatSentence(text=text, citations=()),)
    )


def test_history_pairs_answers_with_their_own_question(tmp_path: Path) -> None:
    # Two concurrent turns can land as Q1, Q2, A1, A2: pairing by position
    # would give A1 to Q2.
    chat_id = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    first = append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="prima"
    )
    second = append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="seconda"
    )
    for question, text in ((first, "risposta alla prima"), (second, "alla seconda")):
        append_answer(
            courses_dir=tmp_path,
            course_id=COURSE,
            chat_id=chat_id,
            reply=AnswerTo(question_id=question.id, answer=_answer(text)),
        )

    turns = history_turns(
        records=load_records(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)
    )

    assert [(t.question, t.sentences[0].text) for t in turns] == [
        ("prima", "risposta alla prima"),
        ("seconda", "alla seconda"),
    ]


def test_answer_after_delete_does_not_resurrect_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    question = append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="domanda"
    )
    path = chat_path(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)
    delete_chat(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)
    # The real race: the existence check passed before the delete landed.
    monkeypatch.setattr(chat_store, "_existing_path", lambda **_: path)

    with pytest.raises(NotFoundError):
        append_answer(
            courses_dir=tmp_path,
            course_id=COURSE,
            chat_id=chat_id,
            reply=AnswerTo(question_id=question.id, answer=_answer("tardi")),
        )

    assert not path.exists()


def test_delete_releases_the_conversation_lock(tmp_path: Path) -> None:
    chat_id = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    path = chat_path(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)
    assert path in chat_store._CHAT_LOCKS

    delete_chat(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)

    assert path not in chat_store._CHAT_LOCKS


def test_title_is_the_first_question_shortened(tmp_path: Path) -> None:
    chat_id = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    long_question = "che cos'è la causa del contratto " * 10
    append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text=long_question
    )
    append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="e poi?"
    )

    [meta] = list_chats(courses_dir=tmp_path, course_id=COURSE)

    assert meta.title.startswith("che cos'è la causa del contratto")
    assert len(meta.title) <= TITLE_MAX_CHARS
    assert meta.title.endswith("…")


def test_title_is_empty_before_any_question(tmp_path: Path) -> None:
    create_chat(courses_dir=tmp_path, course_id=COURSE)

    [meta] = list_chats(courses_dir=tmp_path, course_id=COURSE)

    assert meta.title == ""


def test_answer_record_rejects_negative_discarded_count() -> None:
    with pytest.raises(ValueError, match="discarded"):
        ChatAnswerRecord(
            question_id="q",
            outcome=ChatOutcome.DONE,
            sentences=(),
            discarded=-1,
            error=None,
            created_at="2026-10-03T00:00:00+00:00",
        )


def _drop_meta_line(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if '"kind": "meta"' not in line]
    assert len(kept) == len(lines) - 1
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def test_load_records_skips_blank_lines_silently_and_corrupt_lines_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    chat_id = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    append_question(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="a?")
    path = chat_path(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n   \n{non json\n")
    append_question(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id, text="b?")

    with caplog.at_level(logging.WARNING):
        records = load_records(courses_dir=tmp_path, course_id=COURSE, chat_id=chat_id)

    assert [getattr(record, "text", None) for record in records] == [None, "a?", "b?"]
    assert len(caplog.records) == 1


def test_list_chats_skips_a_conversation_without_meta(tmp_path: Path) -> None:
    kept = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    broken = create_chat(courses_dir=tmp_path, course_id=COURSE).id
    append_question(
        courses_dir=tmp_path, course_id=COURSE, chat_id=broken, text="perso?"
    )
    _drop_meta_line(chat_path(courses_dir=tmp_path, course_id=COURSE, chat_id=broken))

    metas = list_chats(courses_dir=tmp_path, course_id=COURSE)

    assert [meta.id for meta in metas] == [kept]


def test_list_chats_course_without_chats_is_empty(tmp_path: Path) -> None:
    assert list_chats(courses_dir=tmp_path, course_id=COURSE) == []
