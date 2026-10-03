"""Chat records and their JSONL line form, without I/O (T042, ADR D5).

Every line carries a "kind"; a question has its own id and an answer names
the question it replies to.
"""

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from sbobina.chat_pipeline import ChatAnswer, ChatOutcome, ChatSentence
from sbobina.generation_models import GenerationCitation


class ChatRecordKind(StrEnum):
    META = "meta"
    QUESTION = "question"
    ANSWER = "answer"


@dataclass(frozen=True, kw_only=True)
class ChatMeta:
    id: str
    title: str
    created_at: str


@dataclass(frozen=True, kw_only=True)
class ChatQuestionRecord:
    id: str
    text: str
    created_at: str


@dataclass(frozen=True, kw_only=True)
class ChatAnswerRecord:
    question_id: str
    outcome: ChatOutcome
    sentences: tuple[ChatSentence, ...]
    discarded: int
    error: str | None
    created_at: str


ChatRecord = ChatMeta | ChatQuestionRecord | ChatAnswerRecord


@dataclass(frozen=True, kw_only=True)
class AnswerTo:
    """An answer and the question it replies to: two turns of the same chat
    can interleave on disk (Q1, Q2, A1, A2), so position does not pair them."""

    question_id: str
    answer: ChatAnswer


def _citation_to_dict(citation: GenerationCitation) -> dict[str, object]:
    return asdict(citation)


def _citation_from_dict(raw: dict[str, Any]) -> GenerationCitation:
    return GenerationCitation(
        passage_id=str(raw["passage_id"]),
        quote=str(raw["quote"]),
        doc_id=None if raw["doc_id"] is None else str(raw["doc_id"]),
        page=None if raw["page"] is None else int(raw["page"]),
        job_id=None if raw["job_id"] is None else str(raw["job_id"]),
        timestamp=None if raw["timestamp"] is None else float(raw["timestamp"]),
    )


def _sentence_to_dict(sentence: ChatSentence) -> dict[str, object]:
    return {
        "text": sentence.text,
        "citations": [_citation_to_dict(citation=c) for c in sentence.citations],
    }


def _sentence_from_dict(raw: dict[str, Any]) -> ChatSentence:
    citations = raw["citations"]
    assert isinstance(citations, list)
    return ChatSentence(
        text=str(raw["text"]),
        citations=tuple(_citation_from_dict(raw=item) for item in citations),
    )


def record_to_line(record: ChatRecord) -> str:
    if isinstance(record, ChatMeta):
        payload = {"kind": ChatRecordKind.META, **asdict(record)}
    elif isinstance(record, ChatQuestionRecord):
        payload = {"kind": ChatRecordKind.QUESTION, **asdict(record)}
    else:
        payload = {
            "kind": ChatRecordKind.ANSWER,
            "question_id": record.question_id,
            "outcome": record.outcome.value,
            "sentences": [_sentence_to_dict(sentence=s) for s in record.sentences],
            "discarded": record.discarded,
            "error": record.error,
            "created_at": record.created_at,
        }
    return json.dumps(payload, ensure_ascii=False)


def line_to_record(raw: dict[str, Any]) -> ChatRecord:
    kind = ChatRecordKind(raw["kind"])
    if kind is ChatRecordKind.META:
        return ChatMeta(
            id=str(raw["id"]),
            title=str(raw["title"]),
            created_at=str(raw["created_at"]),
        )
    if kind is ChatRecordKind.QUESTION:
        return ChatQuestionRecord(
            id=str(raw["id"]), text=str(raw["text"]), created_at=str(raw["created_at"])
        )
    sentences = raw["sentences"]
    assert isinstance(sentences, list)
    return ChatAnswerRecord(
        question_id=str(raw["question_id"]),
        outcome=ChatOutcome(raw["outcome"]),
        sentences=tuple(_sentence_from_dict(raw=item) for item in sentences),
        discarded=int(raw["discarded"]),
        error=None if raw["error"] is None else str(raw["error"]),
        created_at=str(raw["created_at"]),
    )
