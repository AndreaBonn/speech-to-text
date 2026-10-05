"""LLM-backed generation of exam tasks and summaries (plan C3, T033).

Mirrors study_pipeline.py: the prompt is a versioned file and one retry
absorbs an invalid JSON reply. Per-item validation and citation resolution
(generation_validation.py) turn the parsed response into kept content plus a
discard count by reason. Passage retrieval (course-wide sampling when the
topic is empty) is a separate module built on retrieve_windows, so generate()
stays testable with passages given directly, no I/O.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from importlib import resources

from pydantic import BaseModel, ValidationError

from sbobina.correction import InvalidResponseError
from sbobina.generation_models import (
    DiscardCount,
    GenerationFormat,
    GenerationQuestion,
    GenerationRequest,
    MultipleChoiceResponse,
    SummaryResponse,
    SummarySection,
    TextQuestionResponse,
)
from sbobina.generation_render import format_passage_source
from sbobina.generation_validation import (
    discard_counts,
    validate_exam_response,
    validate_summary_response,
)
from sbobina.ollama_chat import ChatRequest, strip_markdown_fence
from sbobina.retrieval import RetrievedPassage

MAX_ATTEMPTS = 2
# adr.md T001(e): 1500 parole di trascrizione -> 3432 token su qwen3.5:9b.
ITALIAN_TOKENS_PER_WORD = 2.29
INVALID_RESPONSE_ERROR = "INVALID_RESPONSE"

type GenerationChat = Callable[[ChatRequest], str]

PROMPT_FILES: dict[GenerationFormat, str] = {
    GenerationFormat.MULTIPLE_CHOICE: "compito-v3.md",
    GenerationFormat.OPEN: "compito-v3.md",
    GenerationFormat.ORAL: "compito-v3.md",
    GenerationFormat.SUMMARY: "riassunto-v2.md",
}
_FORMAT_LABELS: dict[GenerationFormat, str] = {
    GenerationFormat.MULTIPLE_CHOICE: "crocette",
    GenerationFormat.OPEN: "aperte",
    GenerationFormat.ORAL: "orale",
}
_RESPONSE_SCHEMAS: dict[GenerationFormat, type[BaseModel]] = {
    GenerationFormat.MULTIPLE_CHOICE: MultipleChoiceResponse,
    GenerationFormat.OPEN: TextQuestionResponse,
    GenerationFormat.ORAL: TextQuestionResponse,
    GenerationFormat.SUMMARY: SummaryResponse,
}


class GenerationOutcome(StrEnum):
    DONE = "DONE"
    NO_MATERIAL = "NO_MATERIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, kw_only=True)
class GenerationOptions:
    model: str
    num_predict: int = 1024

    def __post_init__(self) -> None:
        if self.num_predict <= 0:
            raise ValueError("num_predict must be positive")


@dataclass(frozen=True, kw_only=True)
class GenerationResult:
    """Outcome of one call: the caller (T034) assigns an id and persists it."""

    outcome: GenerationOutcome
    model: str
    prompt_version: str
    generated_at: str
    questions: tuple[GenerationQuestion, ...] = ()
    sections: tuple[SummarySection, ...] = ()
    discarded: tuple[DiscardCount, ...] = ()
    error: str | None = None


def estimate_tokens(text: str) -> int:
    """Rough token count for budget checks (2,29 token/parola, adr.md T001e)."""
    return math.ceil(len(text.split()) * ITALIAN_TOKENS_PER_WORD)


def render_passages(passages: Sequence[RetrievedPassage]) -> str:
    """Passages as numbered data, ``[P<n>] (fonte) testo``, one per line."""
    return "\n".join(
        f"[P{index}] ({format_passage_source(source=passage.source)}) {passage.text}"
        for index, passage in enumerate(passages, start=1)
    )


def _build_user_message(
    request: GenerationRequest, passages: Sequence[RetrievedPassage]
) -> str:
    topic = request.topic or "(nessuno)"
    if request.format is GenerationFormat.SUMMARY:
        header = f"Argomento: {topic}."
    else:
        label = _FORMAT_LABELS[request.format]
        header = f"Formato: {label}. Numero: {request.count}. Argomento: {topic}."
    return f"{header}\n{render_passages(passages=passages)}"


def _build_request(
    request: GenerationRequest,
    passages: Sequence[RetrievedPassage],
    options: GenerationOptions,
) -> ChatRequest:
    prompt_file = PROMPT_FILES[request.format]
    system_prompt = (
        resources.files("sbobina.prompts")
        .joinpath(prompt_file)
        .read_text(encoding="utf-8")
    )
    schema_model = _RESPONSE_SCHEMAS[request.format]
    return ChatRequest(
        model=options.model,
        system_prompt=system_prompt,
        user_message=_build_user_message(request=request, passages=passages),
        schema=schema_model.model_json_schema(),
        num_predict=options.num_predict,
    )


def _request_response(
    chat: GenerationChat, request: ChatRequest, schema_model: type[BaseModel]
) -> BaseModel | None:
    for _ in range(MAX_ATTEMPTS):
        try:
            content = strip_markdown_fence(content=chat(request))
            return schema_model.model_validate_json(content)
        except (InvalidResponseError, ValidationError):
            continue
    return None


def _empty_result(
    outcome: GenerationOutcome,
    options: GenerationOptions,
    prompt_version: str,
    generated_at: str,
) -> GenerationResult:
    return GenerationResult(
        outcome=outcome,
        model=options.model,
        prompt_version=prompt_version,
        generated_at=generated_at,
    )


def _apply_validation(
    response: object, passages: Sequence[RetrievedPassage], done: GenerationResult
) -> GenerationResult:
    if isinstance(response, SummaryResponse):
        sections, counts = validate_summary_response(
            response=response, passages=passages
        )
        return replace(done, sections=sections, discarded=discard_counts(counts))
    if isinstance(response, (MultipleChoiceResponse, TextQuestionResponse)):
        questions, counts = validate_exam_response(response=response, passages=passages)
        return replace(done, questions=questions, discarded=discard_counts(counts))
    raise AssertionError(f"unexpected response schema: {type(response)}")


def generate(
    *,
    request: GenerationRequest,
    passages: Sequence[RetrievedPassage],
    chat: GenerationChat,
    options: GenerationOptions,
) -> GenerationResult:
    """Validate and cite one LLM generation; no passages means no call at all."""
    result = partial(
        _empty_result,
        options=options,
        prompt_version=PROMPT_FILES[request.format].removesuffix(".md"),
        generated_at=datetime.now(tz=UTC).isoformat(),
    )
    if not passages:
        return result(outcome=GenerationOutcome.NO_MATERIAL)
    response = _request_response(
        chat=chat,
        request=_build_request(request=request, passages=passages, options=options),
        schema_model=_RESPONSE_SCHEMAS[request.format],
    )
    if response is None:
        failed = result(outcome=GenerationOutcome.FAILED)
        return replace(failed, error=INVALID_RESPONSE_ERROR)
    return _apply_validation(
        response=response,
        passages=passages,
        done=result(outcome=GenerationOutcome.DONE),
    )
