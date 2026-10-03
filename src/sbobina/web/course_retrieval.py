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
from itertools import groupby

from sbobina.course_registry import find_by_key
from sbobina.courses import course_key, effective_course
from sbobina.lecture_windows import (
    WINDOW_WORDS,
    expand_lecture_windows,
    partition_lecture_segments,
)
from sbobina.models import load_transcript
from sbobina.retrieval import (
    DocumentSource,
    LectureSource,
    RetrievalScope,
    RetrievedPassage,
    cut_to_budget,
    fuse_candidates,
    scoped_job_ids,
)
from sbobina.search_text import Passage, passages_from_transcript
from sbobina.source_sampling import sample_across_sources
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.document_index import DocumentScope
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import SearchIndex
from sbobina.web.search_service import PREFERRED_VARIANTS

logger = logging.getLogger(__name__)


# Matches no document row: course ids are uuids, never empty.
NO_REGISTERED_COURSE = ""


def course_scope(store: JobStore, key: str) -> RetrievalScope:
    """Scope of the course with this key: its lectures and its documents.

    Lectures belong by key, with the same mapping /courses uses
    (courses.effective_course + course_key), read fresh from meta.json so a
    rename is reflected without reindexing. Documents belong by registry id:
    a course with lectures only has none, so its scope matches no document.
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
        == key
    )
    course = find_by_key(courses_dir=store.courses_dir, key=key)
    return RetrievalScope(
        course_id=course.id if course is not None else NO_REGISTERED_COURSE,
        job_ids=job_ids,
    )


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


def _document_groups(
    index: SearchIndex, scope: RetrievalScope
) -> list[list[RetrievedPassage]]:
    """One group per document, each in page/chunk reading order."""
    rows = index.course_document_passages(
        scope=DocumentScope(course_id=scope.course_id, doc_ids=scope.selected)
    )
    return [
        [
            RetrievedPassage(
                text=row.text,
                source=DocumentSource(
                    doc_id=row.doc_id, page=row.page, chunk=row.chunk
                ),
                passage_id=row.passage_id,
            )
            for row in doc_rows
        ]
        for _doc_id, doc_rows in groupby(rows, key=lambda row: row.doc_id)
    ]


def _lecture_windows(job_id: str, segments: list[Passage]) -> list[RetrievedPassage]:
    """One RetrievedPassage per consecutive window of this lecture's transcript."""
    spans = partition_lecture_segments(segments=segments, window_words=WINDOW_WORDS)
    windows = []
    for first, last in spans:
        anchor = segments[first]
        windows.append(
            RetrievedPassage(
                text=" ".join(segment.text for segment in segments[first : last + 1]),
                source=LectureSource(
                    job_id=job_id,
                    segment_index=anchor.segment_index,
                    start=anchor.start,
                ),
                passage_id=f"L{job_id}-S{anchor.segment_index}",
            )
        )
    return windows


def _lecture_groups(
    store: JobStore, job_ids: frozenset[str]
) -> list[list[RetrievedPassage]]:
    """One group per lecture, each lecture split into reading-order windows."""
    groups = []
    for job_id in sorted(job_ids):
        segments = _segments_for_job(store=store, job_id=job_id)
        windows = _lecture_windows(job_id=job_id, segments=segments) if segments else []
        if windows:
            groups.append(windows)
    return groups


def sample_course(
    store: JobStore, index: SearchIndex, scope: RetrievalScope, budget_words: int
) -> list[RetrievedPassage]:
    """Course-wide sample across every source, used when the topic is empty.

    Unlike retrieve_windows (which needs a question to match), this reads
    every document and every lecture of the scope and spreads the budget
    across them with source_sampling.sample_across_sources, so a generation
    without a topic still sees material from the whole course.
    """
    groups = _document_groups(index=index, scope=scope) + _lecture_groups(
        store=store, job_ids=scoped_job_ids(scope=scope)
    )
    return sample_across_sources(groups=groups, budget_words=budget_words)
