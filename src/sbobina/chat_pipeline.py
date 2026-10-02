from collections import Counter

"""LLM-backed answer-with-citations for the course chat (plan B-9, T041).

Mirrors generation_pipeline.py: a versioned system prompt, one retry on
invalid JSON, per-sentence citation resolution (one rejected citation drops
only its own sentence, not the whole answer). answer() takes passages
already retrieved (course_retrieval.py stays the only I/O boundary) and
stays pure otherwise. build_retrieval_question() is the one piece of
"understanding" done before retrieval: a short back-reference question
("e quella di prima?") does not carry enough terms on its own.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources

from pydantic import BaseModel, Field, ValidationError

from sbobina.correction import InvalidResponseError
from sbobina.generation_models import (
    GenerationCitation,
    ProposedSummarySentence,
)
from sbobina.generation_pipeline import INVALID_RESPONSE_ERROR, render_passages
from sbobina.generation_validation import (
    resolve_citations,
)
from sbobina.ollama_chat import ChatRequest, strip_markdown_fence
from sbobina.retrieval import RetrievedPassage

PROMPT_FILE = "chat-v1.md"
MAX_ATTEMPTS = 2
# Keeps the prompt bounded regardless of how many passages retrieval hands in.
MAX_PASSAGES = 12
# A longer window would push stale turns into every subsequent prompt; two
# exchanges is enough for "e quella di prima?" without growing unbounded.
MAX_HISTORY_TURNS = 2
# A question this short or shorter is assumed to be a back-reference ("e
# quella di prima?") rather than self-contained: the retrieval query is
# expanded with the previous question's terms. Longer questions are assumed
# to already carry their own terms and are left unchanged.
SHORT_QUESTION_MAX_WORDS = 6
NOT_FOUND_ANSWER = "Non trovo la risposta nel materiale di questo corso."

type ChatClient = Callable[[ChatRequest], str]


class ChatOutcome(StrEnum):
    DONE = "DONE"
    NOT_FOUND = "NOT_FOUND"
    FAILED = "FAILED"


@dataclass(frozen=True, kw_only=True)
class ChatSentence:
    text: str
    citations: tuple[GenerationCitation, ...]


@dataclass(frozen=True, kw_only=True)
class ChatTurn:
    question: str
    sentences: tuple[ChatSentence, ...]


@dataclass(frozen=True, kw_only=True)
class ChatQuery:
    """Bundles the new question with the recent history (max 4 params rule)."""

    question: str
    history: tuple[ChatTurn, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ChatOptions:
    model: str
    num_predict: int = 512

    def __post_init__(self) -> None:
        if self.num_predict <= 0:
            raise ValueError("num_predict must be positive")


@dataclass(frozen=True, kw_only=True)
class ChatAnswer:
    outcome: ChatOutcome
    sentences: tuple[ChatSentence, ...] = ()
    discarded: int = 0
    error: str | None = None


class ChatResponse(BaseModel):
    sentences: list[ProposedSummarySentence] = Field(alias="frasi")


def build_retrieval_question(question: str, history: Sequence[ChatTurn]) -> str:
    """Expand a short back-reference with the previous question's terms.

    A question of at most SHORT_QUESTION_MAX_WORDS words is assumed to refer
    to the previous exchange and is not self-contained for retrieval: the
    returned query is "<last question> <question>". A longer question, or
    one with no history, is returned unchanged.
    """
    if not history or len(question.split()) > SHORT_QUESTION_MAX_WORDS:
        return question
    return f"{history[-1].question} {question}".strip()


def _render_turn(turn: ChatTurn) -> str:
    reply = (
        " ".join(sentence.text for sentence in turn.sentences)
        if turn.sentences
        else NOT_FOUND_ANSWER
    )
    return f"Domanda: {turn.question}\nRisposta: {reply}"


def _build_user_message(
    question: str, history: Sequence[ChatTurn], passages: Sequence[RetrievedPassage]
) -> str:
    recent = history[-MAX_HISTORY_TURNS:]
    parts = [_render_turn(turn) for turn in recent]
    parts.append(f"Domanda: {question}")
    parts.append(render_passages(passages=passages))
    return "\n".join(parts)


def _build_request(
    query: ChatQuery, passages: Sequence[RetrievedPassage], options: ChatOptions
) -> ChatRequest:
    system_prompt = (
        resources.files("sbobina.prompts")
        .joinpath(PROMPT_FILE)
        .read_text(encoding="utf-8")
    )
    user_message = _build_user_message(
        question=query.question, history=query.history, passages=passages
    )
    return ChatRequest(
        model=options.model,
        system_prompt=system_prompt,
        user_message=user_message,
        schema=ChatResponse.model_json_schema(),
        num_predict=options.num_predict,
    )


def _request_response(chat: ChatClient, request: ChatRequest) -> ChatResponse | None:
    for _ in range(MAX_ATTEMPTS):
        try:
            content = strip_markdown_fence(content=chat(request))
            return ChatResponse.model_validate_json(content)
        except (InvalidResponseError, ValidationError):
            continue
    return None


def _validate_sentence(
    proposed: ProposedSummarySentence, passages: Sequence[RetrievedPassage]
) -> ChatSentence | None:
    # Same rule as exams and summaries: one bad citation voids the sentence.
    citations = resolve_citations(
        proposed=proposed.citations, passages=passages, counts=Counter()
    )
    if citations is None:
        return None
    return ChatSentence(text=proposed.text, citations=citations)


def _validate_sentences(
    response: ChatResponse, passages: Sequence[RetrievedPassage]
) -> tuple[tuple[ChatSentence, ...], int]:
    kept = []
    discarded = 0
    for proposed in response.sentences:
        validated = _validate_sentence(proposed=proposed, passages=passages)
        if validated is None:
            discarded += 1
        else:
            kept.append(validated)
    return tuple(kept), discarded


def answer(
    *,
    query: ChatQuery,
    passages: Sequence[RetrievedPassage],
    chat: ChatClient,
    options: ChatOptions,
) -> ChatAnswer:
    """Answer one question; no passages means no call at all (plan B-9)."""
    bounded_passages = tuple(passages[:MAX_PASSAGES])
    if not bounded_passages:
        return ChatAnswer(outcome=ChatOutcome.NOT_FOUND)
    request = _build_request(query=query, passages=bounded_passages, options=options)
    response = _request_response(chat=chat, request=request)
    if response is None:
        return ChatAnswer(outcome=ChatOutcome.FAILED, error=INVALID_RESPONSE_ERROR)
    sentences, discarded = _validate_sentences(
        response=response, passages=bounded_passages
    )
    if not sentences:
        return ChatAnswer(outcome=ChatOutcome.NOT_FOUND, discarded=discarded)
    return ChatAnswer(
        outcome=ChatOutcome.DONE, sentences=sentences, discarded=discarded
    )
