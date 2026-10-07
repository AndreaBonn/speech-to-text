"""One chat turn on a course: persist, retrieve, ask Ollama, persist (T042).

The question is appended before the Ollama call, so it survives a 409, 503
or 504; the answer only on success. Query embedding and local chat each
hold a shared GPU lease for their own Ollama call (T033/R12).
"""

import math
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path

import httpx

from sbobina.chat_pipeline import PROMPT_FILE as CHAT_PROMPT_FILE
from sbobina.chat_pipeline import (
    ChatAnswer,
    ChatClient,
    ChatOptions,
    ChatQuery,
    ChatTurn,
    answer,
    build_retrieval_question,
)
from sbobina.correction import CorrectorUnavailableError
from sbobina.generation_pipeline import ITALIAN_TOKENS_PER_WORD, estimate_tokens
from sbobina.llm_chain import record_served_by
from sbobina.llm_errors import ChainExhaustedError, FailureKind
from sbobina.ollama_chat import CONTEXT_WINDOW_TOKENS, ChatRequest
from sbobina.retrieval import RetrievedPassage
from sbobina.web.chat_records import (
    AnswerTo,
    ChatAnswerRecord,
    ChatQuestionRecord,
    ChatRecord,
)
from sbobina.web.chat_store import append_answer, append_question
from sbobina.web.course_retrieval import (
    WindowedQuery,
    course_scope,
    retrieve_windows_with_report,
)
from sbobina.web.dense_factory import DenseRuntime
from sbobina.web.errors import AppError, GatewayTimeoutError, ServiceUnavailableError
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session

# About six cited sentences: one free-form answer, not the generation
# formats' per-item table.
CHAT_NUM_PREDICT = 768
BUDGET_MARGIN_TOKENS = 512
BUDGET_MIN_WORDS = 200


@dataclass(frozen=True, kw_only=True)
class ChatServices:
    store: JobStore
    index_path: Path
    arbiter: GpuArbiter
    chat_client: ChatClient
    model: str
    # True (local engine): the arbiter guards the whole client, as before api
    # engines existed. False (api engine): the guard already sits on the
    # Ollama link alone, inside the fallback chain built by llm_factory.
    guard_whole_client: bool = True
    dense: DenseRuntime = field(default_factory=DenseRuntime)


@dataclass(frozen=True, kw_only=True)
class ChatLocation:
    key: str
    course_id: str
    chat_id: str


def budget_words(num_predict: int) -> int:
    """Material words left after the chat prompt, the reply and a margin."""
    prompt_text = (
        resources.files("sbobina.prompts")
        .joinpath(CHAT_PROMPT_FILE)
        .read_text(encoding="utf-8")
    )
    available_tokens = (
        CONTEXT_WINDOW_TOKENS
        - estimate_tokens(prompt_text)
        - num_predict
        - BUDGET_MARGIN_TOKENS
    )
    words = math.floor(max(0, available_tokens) / ITALIAN_TOKENS_PER_WORD)
    return max(BUDGET_MIN_WORDS, words)


def history_turns(records: list[ChatRecord]) -> tuple[ChatTurn, ...]:
    """Each answered question with its own answer, in question order; a
    question whose Ollama call failed has no answer and is dropped."""
    answers = {
        record.question_id: record
        for record in records
        if isinstance(record, ChatAnswerRecord)
    }
    return tuple(
        ChatTurn(question=record.text, sentences=answers[record.id].sentences)
        for record in records
        if isinstance(record, ChatQuestionRecord) and record.id in answers
    )


def _guarded(arbiter: GpuArbiter, inner: ChatClient) -> ChatClient:
    def guarded_client(request: ChatRequest) -> str:
        with arbiter.chat_turn():
            return inner(request)

    return guarded_client


def _busy_response(
    error: ChainExhaustedError, arbiter: GpuArbiter
) -> GpuBusyError | None:
    """Same 409 as today's GPU-busy path, when every link failed for that reason.

    ``arbiter.status()`` is read now, not at the time each link failed: if the
    transcription lease has since been released, ``stage`` is None and the
    caller falls back to the generic 503 instead of a stale 409.
    """
    if not error.causes or any(
        cause.kind != FailureKind.BUSY for cause in error.causes
    ):
        return None
    stage, estimate_s = arbiter.status()
    return None if stage is None else GpuBusyError(stage=stage, estimate_s=estimate_s)


def _ollama_error(error: Exception, arbiter: GpuArbiter) -> AppError:
    if isinstance(error, ChainExhaustedError):
        return _busy_response(error=error, arbiter=arbiter) or ServiceUnavailableError(
            message=str(error), code="LLM_UNAVAILABLE"
        )
    if isinstance(error, httpx.TimeoutException) or isinstance(
        error.__cause__, httpx.TimeoutException
    ):
        return GatewayTimeoutError(
            message="Ollama non ha risposto in tempo", code="CHAT_TIMEOUT"
        )
    return ServiceUnavailableError(
        message="Ollama non è raggiungibile", code="OLLAMA_UNAVAILABLE"
    )


def _passages(
    services: ChatServices, key: str, question: str
) -> tuple[list[RetrievedPassage], dict[str, object]]:
    stage, estimate_s = services.arbiter.status()
    if services.guard_whole_client and stage is not None:
        raise GpuBusyError(stage=stage, estimate_s=estimate_s)
    with search_session(store=services.store, path=services.index_path) as index:
        passages, report = retrieve_windows_with_report(
            store=services.store,
            index=index,
            query=WindowedQuery(
                scope=course_scope(store=services.store, key=key),
                question=question,
                budget_words=budget_words(num_predict=CHAT_NUM_PREDICT),
                arbiter=services.arbiter,
            ),
            dense=services.dense.ranker,
        )
    return passages, services.dense.metadata(report=report)


def _answer(
    services: ChatServices, query: ChatQuery, passages: list[RetrievedPassage]
) -> ChatAnswer:
    chat = (
        _guarded(arbiter=services.arbiter, inner=services.chat_client)
        if services.guard_whole_client
        else services.chat_client
    )
    try:
        return answer(
            query=query,
            passages=passages,
            chat=chat,
            options=ChatOptions(model=services.model, num_predict=CHAT_NUM_PREDICT),
        )
    except (ConnectionError, httpx.TransportError, CorrectorUnavailableError) as error:
        raise _ollama_error(error=error, arbiter=services.arbiter) from error


def _reply_to(
    services: ChatServices,
    question_id: str,
    query: ChatQuery,
    passages: list[RetrievedPassage],
) -> AnswerTo:
    """Answer and record which chain link served this turn only."""
    with record_served_by() as served:
        result = _answer(services=services, query=query, passages=passages)
    return AnswerTo(
        question_id=question_id, answer=result, served_by=served.snapshot() or None
    )


def ask(
    services: ChatServices, where: ChatLocation,
    records: list[ChatRecord], question: str,
) -> ChatAnswerRecord:
    """Answer one question in an existing conversation and persist both."""
    courses_dir = services.store.courses_dir
    history = history_turns(records=records)
    asked = append_question(
        courses_dir=courses_dir,
        course_id=where.course_id,
        chat_id=where.chat_id,
        text=question,
    )
    passages, retrieval_mode = _passages(
        services=services,
        key=where.key,
        question=build_retrieval_question(question=question, history=history),
    )
    reply = _reply_to(
        services=services,
        question_id=asked.id,
        query=ChatQuery(question=question, history=history),
        passages=passages,
    )
    return append_answer(
        courses_dir=courses_dir,
        course_id=where.course_id,
        chat_id=where.chat_id,
        reply=replace(reply, retrieval_mode=retrieval_mode),
    )
