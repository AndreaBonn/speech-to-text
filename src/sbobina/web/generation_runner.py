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
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

from sbobina import llm_factory
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    GenerationRequest,
    GenerationSourceUsed,
    GenerationStatus,
)
from sbobina.generation_pipeline import ITALIAN_TOKENS_PER_WORD as TOKENS_PER_WORD
from sbobina.generation_pipeline import (
    PROMPT_FILES,
    GenerationChat,
    GenerationOptions,
    GenerationOutcome,
    GenerationResult,
    estimate_tokens,
    generate,
)
from sbobina.llm_chain import ServedByRecorder
from sbobina.ollama_chat import CONTEXT_WINDOW_TOKENS
from sbobina.retrieval import (
    DocumentSource,
    LectureSource,
    RetrievedPassage,
)
from sbobina.runtime_config import runtime_settings
from sbobina.settings import settings
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.dense_factory import DenseRuntime, dense_for_process
from sbobina.web.document_store import read_document
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_sources import (
    GenerationRetrieval,
    retrieve_generation_passages,
)
from sbobina.web.generation_store import find_running, save_generation
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session

# Measured on qwen3.5:9b (T036, specs/001-course-workspace/eval-generations.md):
# 10 multiple-choice items were cut at 1756 tokens (over 175 each), 10 oral
# items used 2251 (225 each), 10 open items 1068 (about 107 each).
NUM_PREDICT_PER_ITEM: dict[GenerationFormat, int] = {
    GenerationFormat.MULTIPLE_CHOICE: 260,
    GenerationFormat.OPEN: 200,
    GenerationFormat.ORAL: 280,
}
NUM_PREDICT_MARGIN_TOKENS = 256
NUM_PREDICT_MIN = 512
# A summary is one item regardless of requested_count (there is no "count" of
# sections), so the per-item formula starved it at 556 tokens: Ollama
# truncated the real reply (done_reason=length), which validate() then
# rejected as INVALID_RESPONSE. Fixed instead of scaled with count; a
# summary of one lecture then still reached 2048 (T036), hence 2560.
SUMMARY_NUM_PREDICT = 2560
BUDGET_MARGIN_TOKENS = 512
BUDGET_MIN_WORDS = 200
SEARCH_INDEX_FILENAME = "search.sqlite3"
COURSE_FILENAME = "course.json"


def compute_options(
    count: int, format_: GenerationFormat, model: str
) -> GenerationOptions:
    """num_predict scales with how much content was requested.

    A summary has no per-item count (one set of sections, not `count`
    questions): it gets the fixed SUMMARY_NUM_PREDICT instead.
    """
    if format_ is GenerationFormat.SUMMARY:
        return GenerationOptions(model=model, num_predict=SUMMARY_NUM_PREDICT)
    per_item = NUM_PREDICT_PER_ITEM[format_]
    num_predict = max(NUM_PREDICT_MIN, count * per_item + NUM_PREDICT_MARGIN_TOKENS)
    return GenerationOptions(model=model, num_predict=num_predict)


def compute_budget_words(format_: GenerationFormat, options: GenerationOptions) -> int:
    """Passage word budget left after the system prompt and the reply."""
    prompt_text = (
        resources.files("sbobina.prompts")
        .joinpath(PROMPT_FILES[format_])
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
    recorder: ServedByRecorder | None = None


def _status_for_outcome(outcome: GenerationOutcome) -> GenerationStatus:
    return (
        GenerationStatus.FAILED
        if outcome is GenerationOutcome.FAILED
        else GenerationStatus.DONE
    )


def _to_record(
    record: GenerationRecord,
    result: GenerationResult,
    sources: tuple[GenerationSourceUsed, ...],
) -> GenerationRecord:
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
        sources=sources,
    )


def build_sources(
    passages: list[RetrievedPassage],
    doc_sha256: Callable[[str], str | None],
    find_lecture_revision: Callable[[str], str | None],
) -> tuple[GenerationSourceUsed, ...]:
    """Every distinct source among the passages handed to the model (ADR D5).

    Includes uncited material to detect source changes; missing sources are dropped.
    """
    doc_ids = frozenset(
        passage.source.doc_id
        for passage in passages
        if isinstance(passage.source, DocumentSource)
    )
    job_ids = frozenset(
        passage.source.job_id
        for passage in passages
        if isinstance(passage.source, LectureSource)
    )
    documents = (
        GenerationSourceUsed(doc_id=doc_id, sha256=sha256, job_id=None, revision=None)
        for doc_id in sorted(doc_ids)
        if (sha256 := doc_sha256(doc_id)) is not None
    )
    lectures = (
        GenerationSourceUsed(doc_id=None, sha256=None, job_id=job_id, revision=revision)
        for job_id in sorted(job_ids)
        if (revision := find_lecture_revision(job_id)) is not None
    )
    return (*documents, *lectures)


def _collect_sources(
    job: GenerationJob, passages: list[RetrievedPassage]
) -> tuple[GenerationSourceUsed, ...]:
    def doc_sha256(doc_id: str) -> str | None:
        try:
            return read_document(
                courses_dir=job.store.courses_dir,
                course_id=job.course_id,
                doc_id=doc_id,
            ).sha256
        except NotFoundError:
            return None

    def find_lecture_revision(job_id: str) -> str | None:
        return lecture_revision(store=job.store, job_id=job_id)

    return build_sources(
        passages=passages,
        doc_sha256=doc_sha256,
        find_lecture_revision=find_lecture_revision,
    )


def execute_generation(
    job: GenerationJob,
    chat: GenerationChat,
    model: str,
    dense: DenseRuntime | None = None,
) -> None:
    """Retrieve passages for job.record's request and persist the result."""
    request = GenerationRequest(
        format=job.record.format,
        count=job.record.requested_count,
        topic=job.record.topic,
        sources=job.record.requested_sources,
    )
    options = compute_options(count=request.count, format_=request.format, model=model)
    budget_words = compute_budget_words(format_=request.format, options=options)
    with search_session(store=job.store, path=job.index_path) as index:
        passages, retrieval_mode = retrieve_generation_passages(
            context=GenerationRetrieval(job=job, dense=dense or DenseRuntime()),
            index=index,
            request=request,
            budget_words=budget_words,
        )
    result = generate(request=request, passages=passages, chat=chat, options=options)
    sources = _collect_sources(job=job, passages=passages)
    save_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        record=replace(
            _to_record(record=job.record, result=result, sources=sources),
            served_by=(job.recorder.snapshot() or None) if job.recorder else None,
            retrieval_mode=retrieval_mode,
        ),
    )


def _course_key(courses_dir: Path, course_id: str) -> str:
    content = (courses_dir / course_id / COURSE_FILENAME).read_text(encoding="utf-8")
    return str(json.loads(content)["key"])


def run_generation_stage(course_dir: Path) -> None:
    """Production entry point: course_dir is courses/<course_id>."""
    courses_dir, course_id = course_dir.parent, course_dir.name
    data_dir = courses_dir.parent
    job = GenerationJob(
        store=JobStore(data_dir=data_dir),
        index_path=data_dir / SEARCH_INDEX_FILENAME,
        course_id=course_id,
        course_key=_course_key(courses_dir=courses_dir, course_id=course_id),
        record=find_running(courses_dir=courses_dir, course_id=course_id),
        recorder=ServedByRecorder(),
    )
    config = runtime_settings(settings=settings)
    chat = llm_factory.build_from_settings(settings=config, recorder=job.recorder)
    label = llm_factory.effective_model_label(settings=config)
    execute_generation(
        job=job,
        chat=chat,
        model=label,
        dense=dense_for_process(settings=config, data_dir=data_dir),
    )


__all__ = [
    "GenerationJob",
    "build_sources",
    "compute_budget_words",
    "compute_options",
    "execute_generation",
    "run_generation_stage",
]
