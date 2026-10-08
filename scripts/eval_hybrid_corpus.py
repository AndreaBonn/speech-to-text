"""Course corpus boundary for scripts/eval_hybrid.py (T013, specs/004-hybrid-retrieval).

Document and lecture candidate universes for one course: the SearchIndex/
JobStore I/O that builds the BM25 and dense candidate lists eval_hybrid.py
ranks. Split out of eval_hybrid.py to keep each file under the 300-line
limit; see that module's docstring for the document/lecture unit framing.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sbobina.embedding_units import (
    DocUnit,
    EvalUnit,
    LectureUnit,
    aggregate_lecture_hits_to_windows,
    build_lecture_units,
    segment_positions,
)
from sbobina.hybrid_eval import (
    RankedUnits,
)
from sbobina.lecture_windows import WINDOW_WORDS
from sbobina.models import load_transcript
from sbobina.retrieval import RetrievalScope, scoped_job_ids
from sbobina.retrieval_metrics import DocumentRef
from sbobina.search_text import Passage
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.course_retrieval import course_scope
from sbobina.web.document_index import DocumentScope
from sbobina.web.document_store import iter_documents
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import SearchIndex
from sbobina.web.search_service import PREFERRED_VARIANTS

# Universe-sized, not a word-budget cut: dense ranks the whole course, and no
# real course has anywhere near this many passages or windows (plan.md
# Research: 2.5-3k units for a semester course).
CANDIDATE_LIMIT = 10_000


def doc_filenames(courses_dir: Path, course_id: str) -> dict[str, str]:
    return {
        doc.id: doc.filename
        for doc in iter_documents(courses_dir=courses_dir, course_id=course_id)
    }


def doc_universe(
    index: SearchIndex, scope: RetrievalScope, filenames: dict[str, str]
) -> list[DocUnit]:
    rows = index.course_document_passages(
        scope=DocumentScope(course_id=scope.course_id, doc_ids=scope.selected)
    )
    return [
        DocUnit(
            passage_id=row.passage_id,
            text=row.text,
            ref=DocumentRef(filename=filenames[row.doc_id], page=row.page),
        )
        for row in rows
    ]


def doc_bm25(
    index: SearchIndex, scope: RetrievalScope, match: str, filenames: dict[str, str]
) -> RankedUnits:
    rows = index.document_passages_for_retrieval(
        match=match,
        scope=DocumentScope(course_id=scope.course_id, doc_ids=scope.selected),
        limit=CANDIDATE_LIMIT,
    )
    return [
        (
            row.score,
            DocUnit(
                passage_id=row.passage_id,
                text=row.text,
                ref=DocumentRef(filename=filenames[row.doc_id], page=row.page),
            ),
        )
        for row in rows
    ]


def lecture_segments_and_ends(
    store: JobStore, job_id: str
) -> tuple[list[Passage], list[float]]:
    """One lecture's non-empty segments and their end times, position-aligned.

    Mirrors search_text.passages_from_transcript's filter so position i in
    both the returned Passage list and the end-time list refers to the same
    segment; Passage itself has no end field (see embedding_units.build_lecture_units).
    """
    directory = store.jobs_dir / job_id
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        if not path.exists():
            continue
        transcript = load_transcript(path=path)
        segments, ends = [], []
        for index, segment in enumerate(transcript.segments):
            if not segment.text:
                continue
            segments.append(
                Passage(segment_index=index, start=segment.start, text=segment.text)
            )
            ends.append(segment.end)
        return segments, ends
    # An in-scope lecture with no transcript would add zero units and turn its
    # gold questions into misses that look like ranking failures.
    raise FileNotFoundError(f"no transcript for lecture {job_id} in {directory}")


@dataclass
class LectureIndex:
    spans: list[tuple[int, int]]
    units: list[LectureUnit]
    positions: dict[int, int]


def build_lecture_index(store: JobStore, job_id: str) -> LectureIndex:
    segments, ends = lecture_segments_and_ends(store=store, job_id=job_id)
    spans, units = build_lecture_units(
        job_id=job_id, segments=segments, segment_ends=ends, window_words=WINDOW_WORDS
    )
    return LectureIndex(
        spans=spans, units=units, positions=segment_positions(segments=segments)
    )


def lecture_bm25(
    index: SearchIndex,
    scope: RetrievalScope,
    match: str,
    lecture_indexes: dict[str, LectureIndex],
) -> RankedUnits:
    job_ids = scoped_job_ids(scope=scope)
    if not job_ids:
        return []
    rows = index.lecture_passages_for_retrieval(
        match=match, job_ids=job_ids, limit=CANDIDATE_LIMIT
    )
    hits_by_job: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for row in rows:
        hits_by_job[row.job_id].append((row.score, row.segment_index))
    results: list[tuple[float, LectureUnit]] = []
    for job_id, hits in hits_by_job.items():
        lecture_index = lecture_indexes[job_id]
        results.extend(
            aggregate_lecture_hits_to_windows(
                hits=hits,
                segment_positions=lecture_index.positions,
                spans=lecture_index.spans,
                units=lecture_index.units,
            )
        )
    return results


@dataclass
class CourseContext:
    index: SearchIndex
    scope: RetrievalScope
    filenames: dict[str, str]
    doc_units: list[DocUnit]
    lecture_indexes: dict[str, LectureIndex]

    def all_units(self) -> list[EvalUnit]:
        lecture_units = [
            unit for li in self.lecture_indexes.values() for unit in li.units
        ]
        return [*self.doc_units, *lecture_units]


def build_course_context(
    store: JobStore, index: SearchIndex, key: str
) -> CourseContext:
    scope = course_scope(store=store, key=key)
    filenames = doc_filenames(courses_dir=store.courses_dir, course_id=scope.course_id)
    doc_units = doc_universe(index=index, scope=scope, filenames=filenames)
    lecture_indexes = {
        job_id: build_lecture_index(store=store, job_id=job_id)
        for job_id in sorted(scoped_job_ids(scope=scope))
    }
    return CourseContext(
        index=index,
        scope=scope,
        filenames=filenames,
        doc_units=doc_units,
        lecture_indexes=lecture_indexes,
    )
