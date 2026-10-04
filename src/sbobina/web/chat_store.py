"""Append-only JSONL persistence for course chat conversations (T042, D5).

One file per conversation: ``courses/<course_id>/chats/<chat_id>.jsonl``. The
first line is a ``meta`` record written once at creation (id/title/created_at
have no other stable home, since the file's own mtime moves on every
append); every following line is a ``question`` or an ``answer`` record, one
per message, never rewritten. A question is appended before the Ollama call
that answers it, so it survives even when that call fails; the matching
answer is appended only on success. Writers on the same conversation take a
lock scoped to the open+append, not to the whole request, so two concurrent
POSTs on the same chat both land their own line instead of one clobbering
the other mid-write.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sbobina.web.chat_records import (
    AnswerTo,
    ChatAnswerRecord,
    ChatMeta,
    ChatQuestionRecord,
    ChatRecord,
    line_to_record,
    record_to_line,
)
from sbobina.web.errors import NotFoundError
from sbobina.web.path_locks import _LOCKS_GUARD, _PATH_LOCKS, lock_for

logger = logging.getLogger("sbobina")

CHATS_DIRNAME = "chats"
TITLE_MAX_CHARS = 60
_CHAT_LOCKS = _PATH_LOCKS


def chats_dir(courses_dir: Path, course_id: str) -> Path:
    return courses_dir / course_id / CHATS_DIRNAME


def chat_path(courses_dir: Path, course_id: str, chat_id: str) -> Path:
    return chats_dir(courses_dir=courses_dir, course_id=course_id) / f"{chat_id}.jsonl"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _append(path: Path, record: ChatRecord) -> None:
    """Append under the conversation lock; a deleted chat stays deleted.

    Mode "a" would recreate a file deleted while a slow Ollama call was in
    flight, leaving a chat with no meta line that nobody can list or delete.
    """
    line = record_to_line(record=record)
    with lock_for(path=path):
        if not isinstance(record, ChatMeta) and not path.is_file():
            raise NotFoundError(entity="Chat", id=path.stem)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def create_chat(courses_dir: Path, course_id: str) -> ChatMeta:
    chat_id = str(uuid4())
    path = chat_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = ChatMeta(id=chat_id, title="", created_at=_now())
    _append(path=path, record=meta)
    return meta


def append_question(
    courses_dir: Path, course_id: str, chat_id: str, text: str
) -> ChatQuestionRecord:
    path = _existing_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    record = ChatQuestionRecord(id=str(uuid4()), text=text, created_at=_now())
    _append(path=path, record=record)
    return record


def append_answer(
    courses_dir: Path, course_id: str, chat_id: str, reply: AnswerTo
) -> ChatAnswerRecord:
    path = _existing_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    record = ChatAnswerRecord(
        question_id=reply.question_id,
        outcome=reply.answer.outcome,
        sentences=reply.answer.sentences,
        discarded=reply.answer.discarded,
        error=reply.answer.error,
        created_at=_now(),
    )
    _append(path=path, record=record)
    return record


def _existing_path(courses_dir: Path, course_id: str, chat_id: str) -> Path:
    path = chat_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    if not path.is_file():
        raise NotFoundError(entity="Chat", id=chat_id)
    return path


def load_records(courses_dir: Path, course_id: str, chat_id: str) -> list[ChatRecord]:
    """Every record of one conversation, in append order.

    A corrupt or unreadable line is skipped with a warning instead of
    failing the whole read: one bad append must not hide every other
    message in the conversation.
    """
    path = _existing_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    records: list[ChatRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(line_to_record(raw=json.loads(line)))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
            logger.warning("Riga di chat non leggibile, salto: %s", error)
    return records


def _title(records: list[ChatRecord]) -> str:
    first = next((r for r in records if isinstance(r, ChatQuestionRecord)), None)
    if first is None:
        return ""
    text = " ".join(first.text.split())
    if len(text) <= TITLE_MAX_CHARS:
        return text
    return text[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def chat_meta(records: list[ChatRecord]) -> ChatMeta | None:
    """The conversation's meta line, titled after its first question."""
    meta = next((r for r in records if isinstance(r, ChatMeta)), None)
    if meta is None:
        return None
    return replace(meta, title=meta.title or _title(records=records))


def read_meta(courses_dir: Path, course_id: str, chat_id: str) -> ChatMeta:
    meta = chat_meta(
        records=load_records(
            courses_dir=courses_dir, course_id=course_id, chat_id=chat_id
        )
    )
    if meta is None:
        raise NotFoundError(entity="Chat", id=chat_id)
    return meta


def _chat_ids(courses_dir: Path, course_id: str) -> Iterator[str]:
    directory = chats_dir(courses_dir=courses_dir, course_id=course_id)
    if not directory.is_dir():
        return
    for path in directory.glob("*.jsonl"):
        yield path.stem


def list_chats(courses_dir: Path, course_id: str) -> list[ChatMeta]:
    """Every conversation's meta record, newest first."""
    metas = []
    for chat_id in _chat_ids(courses_dir=courses_dir, course_id=course_id):
        try:
            metas.append(
                read_meta(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
            )
        except NotFoundError:
            continue
    metas.sort(key=lambda meta: meta.created_at, reverse=True)
    return metas


def delete_chat(courses_dir: Path, course_id: str, chat_id: str) -> None:
    path = _existing_path(courses_dir=courses_dir, course_id=course_id, chat_id=chat_id)
    with lock_for(path=path):
        path.unlink(missing_ok=True)
    with _LOCKS_GUARD:
        _CHAT_LOCKS.pop(path, None)
