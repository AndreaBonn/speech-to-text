"""Child-process execution of the "generation" stage.

Mirrors study_stage.py's role for the study stage: build the retrieval
budget, run generate(), persist the resulting GenerationRecord. The citation
timestamps generate() returns are already fully resolved by
generation_validation.py/source_citations.py against the anchor segment
retrieval matched (see source_citations.py's module docstring): no further
study_citations.locate_quote call is needed here.
"""

import json
import math
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

from ollama import Client

from sbobina import llm_corrector, ollama_chat
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.generation_pipeline import ITALIAN_TOKENS_PER_WORD as TOKENS_PER_WORD
from sbobina.generation_pipeline import (
    GenerationChat,
    GenerationOptions,
    GenerationOutcome,
    GenerationResult,
    estimate_tokens,
    generate,
)
from sbobina.ollama_chat import CONTEXT_WINDOW_TOKENS
from sbobina.settings import settings
from sbobina.web.course_retrieval import WindowedQuery, course_scope, retrieve_windows
from sbobina.web.generation_store import find_running, save_generation
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session

_PROMPT_FILES: dict[GenerationFormat, str] = {
    GenerationFormat.MULTIPLE_CHOICE: "compito-v1.md",
    GenerationFormat.OPEN: "compito-v1.md",
    GenerationFormat.ORAL: "compito-v1.md",
    GenerationFormat.SUMMARY: "riassunto-v1.md",
}
NUM_PREDICT_PER_ITEM: dict[GenerationFormat, int] = {
    GenerationFormat.MULTIPLE_CHOICE: 150,
    GenerationFormat.OPEN: 200,
    GenerationFormat.ORAL: 220,
    GenerationFormat.SUMMARY: 300,
}
NUM_PREDICT_MARGIN_TOKENS = 256
NUM_PREDICT_MIN = 512
BUDGET_MARGIN_TOKENS = 512
BUDGET_MIN_WORDS = 200
SEARCH_INDEX_FILENAME = "search.sqlite3"
COURSE_FILENAME = "course.json"


def compute_options(
    count: int, format_: GenerationFormat, model: str
) -> GenerationOptions:
    """num_predict scales with how much content was requested."""
    per_item = NUM_PREDICT_PER_ITEM[format_]
    num_predict = max(NUM_PREDICT_MIN, count * per_item + NUM_PREDICT_MARGIN_TOKENS)
    return GenerationOptions(model=model, num_predict=num_predict)


def compute_budget_words(format_: GenerationFormat, options: GenerationOptions) -> int:
    """Passage word budget left after the system prompt and the reply."""
    prompt_text = (
        resources.files("sbobina.prompts")
        .joinpath(_PROMPT_FILES[format_])
        .read_text(encoding="utf-8")
    )
    available_tokens = (
        CONTEXT_WINDOW_TOKENS
        - estimate_tokens(prompt_text)
        - options.num_predict
        - BUDGET_MARGIN_TOKENS
    )
    words = math.floor(max(0, available_tokens) / TOKENS_PER_WORD)
    return max(BUDGET_MIN_WORDS, words)


@dataclass(frozen=True, kw_only=True)
class GenerationJob:
    store: JobStore
    index_path: Path
    course_id: str
    course_key: str
    record: GenerationRecord


def _status_for_outcome(outcome: GenerationOutcome) -> GenerationStatus:
    return (
        GenerationStatus.FAILED
        if outcome is GenerationOutcome.FAILED
        else GenerationStatus.DONE
    )


def _to_record(record: GenerationRecord, result: GenerationResult) -> GenerationRecord:
    # sources (GenerationSourceUsed, sha256/revision) stays empty here: it
    # needs per-document hashing not wired into this half of the stage.
    return replace(
        record,
        status=_status_for_outcome(result.outcome),
        model=result.model,
        prompt_version=result.prompt_version,
        generated_at=result.generated_at,
        questions=result.questions,
        sections=result.sections,
        discarded=result.discarded,
        error=result.error,
    )


def execute_generation(job: GenerationJob, chat: GenerationChat, model: str) -> None:
    """Retrieve passages for job.record's request and persist the result."""
    request = GenerationRequest(
        format=job.record.format,
        count=job.record.requested_count,
        topic=job.record.topic,
    )
    options = compute_options(count=request.count, format_=request.format, model=model)
    budget_words = compute_budget_words(format_=request.format, options=options)
    with search_session(store=job.store, path=job.index_path) as index:
        scope = course_scope(store=job.store, key=job.course_key)
        passages = retrieve_windows(
            store=job.store,
            index=index,
            query=WindowedQuery(
                scope=scope, question=request.topic, budget_words=budget_words
            ),
        )
    result = generate(request=request, passages=passages, chat=chat, options=options)
    save_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        record=_to_record(record=job.record, result=result),
    )


def _course_key(courses_dir: Path, course_id: str) -> str:
    content = (courses_dir / course_id / COURSE_FILENAME).read_text(encoding="utf-8")
    return str(json.loads(content)["key"])


def _build_chat(model: str, host: str) -> GenerationChat:
    llm_corrector.ensure_model(model=model, host=host)
    client = Client(host=host)
    return lambda request: ollama_chat.chat_json(client=client, request=request)


def run_generation_stage(course_dir: Path) -> None:
    """Production entry point: course_dir is courses/<course_id>."""
    courses_dir = course_dir.parent
    data_dir = courses_dir.parent
    course_id = course_dir.name
    store = JobStore(data_dir=data_dir)
    record = find_running(courses_dir=courses_dir, course_id=course_id)
    job = GenerationJob(
        store=store,
        index_path=data_dir / SEARCH_INDEX_FILENAME,
        course_id=course_id,
        course_key=_course_key(courses_dir=courses_dir, course_id=course_id),
        record=record,
    )
    chat = _build_chat(model=settings.ollama_model, host=settings.ollama_host)
    execute_generation(job=job, chat=chat, model=settings.ollama_model)


__all__ = [
    "GenerationJob",
    "compute_budget_words",
    "compute_options",
    "execute_generation",
    "run_generation_stage",
]
