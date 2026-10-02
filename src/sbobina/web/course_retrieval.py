"""Build a course's retrieval scope from the job store, and run a windowed
question over it.

Callers (chat, exam-task flows, T024+) compose this with
search_service.search_session (lock + reconciliation) and retrieval.retrieve:
no new locking here, the lock already lives in search_service. This module
is the I/O edge for T025 (ADR D2, tabella Chunking): it reads each matched
lecture's transcript once per call and hands the segments to the pure
sbobina.lecture_windows.expand_lecture_windows.
"""

import logging
from dataclasses import dataclass

from sbobina.courses import course_key, effective_course
from sbobina.lecture_windows import WINDOW_WORDS, expand_lecture_windows
from sbobina.models import load_transcript
from sbobina.retrieval import (
    LectureSource,
    RetrievalScope,
    RetrievedPassage,
    cut_to_budget,
    fuse_candidates,
)
from sbobina.search_text import Passage, passages_from_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import SearchIndex
from sbobina.web.search_service import PREFERRED_VARIANTS

logger = logging.getLogger(__name__)


def course_scope(store: JobStore, course_id: str) -> RetrievalScope:
    """Scope of one course: every lecture whose effective course matches it.

    Same mapping /courses uses (courses.effective_course + course_key), read
    fresh from meta.json so a rename is reflected without reindexing.
    """
    job_ids = frozenset(
        str(record.id)
        for record in store.iter_records()
        if course_key(
            label=effective_course(
                course=store.read_meta(job_id=str(record.id)).course,
                subject=record.config.subject,
            )
        )
        == course_id
    )
    return RetrievalScope(course_id=course_id, job_ids=job_ids)


def _segments_for_job(store: JobStore, job_id: str) -> list[Passage]:
    """Segments of one lecture's best transcript, or [] when unreadable now."""
    directory = store.jobs_dir / job_id
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        if not path.exists():
            continue
        try:
            return passages_from_transcript(transcript=load_transcript(path=path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Trascrizione non leggibile, salto %s: %s", path, error)
            return []
    return []


def _segments_by_job(
    store: JobStore, hits: list[RetrievedPassage]
) -> dict[str, list[Passage]]:
    job_ids = {
        hit.source.job_id for hit in hits if isinstance(hit.source, LectureSource)
    }
    return {job_id: _segments_for_job(store=store, job_id=job_id) for job_id in job_ids}


@dataclass(frozen=True)
class WindowedQuery:
    scope: RetrievalScope
    question: str
    budget_words: int


def retrieve_windows(
    store: JobStore, index: SearchIndex, query: WindowedQuery
) -> list[RetrievedPassage]:
    """Course passages for a question, lecture hits expanded to ~250-word windows.

    Windows are built before the word budget is applied: the budget counts
    window words, not the raw 10-30 word Whisper segment that matched.
    """
    fused = fuse_candidates(index=index, scope=query.scope, question=query.question)
    segments_by_job = _segments_by_job(store=store, hits=fused)
    windows = expand_lecture_windows(
        hits=fused, segments_by_job=segments_by_job, window_words=WINDOW_WORDS
    )
    return cut_to_budget(ranked=windows, budget_words=query.budget_words)
