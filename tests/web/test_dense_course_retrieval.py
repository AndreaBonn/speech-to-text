from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from dense_retrieval_fixtures import COURSE, document, populate, ranker
from vector_reconcile_fixtures import write_course, write_lecture

from sbobina.document_passages import DocumentPassage
from sbobina.retrieval import (
    LectureSource,
    RetrievalScope,
    RetrievedPassage,
    question_to_fts,
)
from sbobina.search_text import Passage
from sbobina.web.course_retrieval import (
    WindowedQuery,
    course_scope,
    retrieve_windows,
    retrieve_windows_with_report,
)
from sbobina.web.dense_retrieval import DenseRanker
from sbobina.web.document_index import DocumentState
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import LectureState, SearchIndex, open_index
from sbobina.web.vector_store import Coverage, VectorStore


@dataclass
class CourseCase:
    store: JobStore
    index: SearchIndex
    dense: DenseRanker
    vectors: VectorStore
    query: WindowedQuery


@pytest.fixture
def case(tmp_path: Path) -> Iterator[CourseCase]:
    store = JobStore(data_dir=tmp_path)
    course = write_course(store=store)
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        index.replace_document(
            doc_id="document",
            state=DocumentState(course_id=course.id, text_mtime_ns=1, text_size=1),
            passages=[
                DocumentPassage(
                    passage_id=document(number=i).passage_id,
                    page=1,
                    chunk=i,
                    text=document(number=i).text,
                )
                for i in range(2)
            ],
        )
        query = WindowedQuery(
            scope=course_scope(store=store, key=COURSE),
            question="contratto",
            budget_words=1000,
        )
        yield CourseCase(
            store=store, index=index, dense=dense, vectors=vectors, query=query
        )
    vectors.close()


def test_retrieve_dense_without_fts_terms_and_budget(case: CourseCase) -> None:
    docs = [document(number=i) for i in range(2)]
    populate(vectors=case.vectors, passages=docs, values=[(0.6, 0.8), (1.0, 0.0)])
    query = replace(case.query, question="di e la", budget_words=3)
    assert question_to_fts(question=query.question) is None

    result, report = retrieve_windows_with_report(
        case.store, case.index, query, dense=case.dense
    )

    assert result == [docs[1]]
    assert (report.mode, report.reason, report.coverage) == (
        "dense",
        None,
        Coverage(embedded=2, total=2, truncated=0),
    )
    assert retrieve_windows(case.store, case.index, query, dense=case.dense) == result
    assert retrieve_windows(case.store, case.index, query) == []


def test_retrieve_partial_course_preserves_bm25_results(case: CourseCase) -> None:
    docs = [document(number=i) for i in range(120)]
    populate(vectors=case.vectors, passages=docs, values=[(1.0, 0.0)] * 118)
    expected = retrieve_windows(case.store, case.index, case.query)

    result, report = retrieve_windows_with_report(
        case.store, case.index, case.query, dense=case.dense
    )

    assert result == expected == docs[:2]
    assert (report.mode, report.reason, report.coverage) == (
        "bm25",
        "partial",
        Coverage(embedded=118, total=120, truncated=0),
    )


def test_retrieve_no_dense_reports_plain_bm25(case: CourseCase) -> None:
    result, report = retrieve_windows_with_report(case.store, case.index, case.query)

    assert result == [document(number=i) for i in range(2)]
    assert (report.mode, report.reason, report.coverage) == ("bm25", None, None)


def _partitioned_lecture(case: CourseCase) -> list[RetrievedPassage]:
    texts = [(f"segment{i} " * 140).strip() for i in range(3)]
    path = write_lecture(store=case.store, texts=texts)
    job_id = path.parent.name
    case.index.replace_lecture(
        job_id=job_id,
        state=LectureState(variant="original", path_mtime_ns=1, path_size=1),
        passages=[
            Passage(segment_index=i, start=float(i), text=text)
            for i, text in enumerate(texts)
        ],
    )
    return [
        RetrievedPassage(
            text=" ".join(texts[first : last + 1]),
            source=LectureSource(
                job_id=job_id, segment_index=first, start=float(first)
            ),
            passage_id=f"L{job_id}-S{first}",
        )
        for first, last in [(0, 1), (2, 2)]
    ]


def test_retrieve_lecture_keeps_partition_tail_without_growth(case: CourseCase) -> None:
    windows = _partitioned_lecture(case=case)
    docs = [document(number=i) for i in range(2)]
    populate(
        vectors=case.vectors,
        passages=docs + windows,
        values=[(0.0, 1.0)] * 3 + [(1.0, 0.0)],
    )
    query = replace(
        case.query, scope=course_scope(store=case.store, key=COURSE), budget_words=140
    )

    result, report = retrieve_windows_with_report(
        case.store, case.index, query, dense=case.dense
    )

    assert report.mode == "dense"
    assert result == [windows[1]]
    assert len(result[0].text.split()) == 140
    assert "segment0" not in result[0].text and "segment1" not in result[0].text
    assert result[0].text == " ".join(["segment2"] * 140)


def test_retrieve_selected_filters_lectures_and_documents(case: CourseCase) -> None:
    first = _partitioned_lecture(case=case)
    second = _partitioned_lecture(case=case)
    docs = [document(number=i) for i in range(2)]
    populate(
        vectors=case.vectors, passages=docs + first + second, values=[(1.0, 0.0)] * 6
    )
    source = first[0].source
    assert isinstance(source, LectureSource)
    scope = replace(
        course_scope(store=case.store, key=COURSE), selected=frozenset({source.job_id})
    )

    result, report = retrieve_windows_with_report(
        case.store, case.index, replace(case.query, scope=scope), dense=case.dense
    )

    assert result == first
    assert report.coverage == Coverage(embedded=6, total=6, truncated=0)
    doc_scope = replace(scope, selected=frozenset({"document"}))
    assert (
        retrieve_windows(
            case.store,
            case.index,
            replace(case.query, scope=doc_scope),
            dense=case.dense,
        )
        == docs
    )


def test_retrieve_partial_course_still_falls_back_with_complete_selection(
    case: CourseCase,
) -> None:
    docs = [document(number=i) for i in range(3)]
    populate(vectors=case.vectors, passages=docs, values=[(1.0, 0.0)] * 2)
    query = replace(
        case.query, scope=replace(case.query.scope, selected=frozenset({"document"}))
    )

    result, report = retrieve_windows_with_report(
        case.store, case.index, query, dense=case.dense
    )

    assert result == docs[:2]
    assert report.reason == "partial"


def test_retrieve_lecture_only_course_resolves_key_without_registry_id(
    case: CourseCase,
) -> None:
    windows = _partitioned_lecture(case=case)
    source = windows[0].source
    assert isinstance(source, LectureSource)
    populate(vectors=case.vectors, passages=windows, values=[(1.0, 0.0)] * 2)
    scope = RetrievalScope(course_id="", job_ids=frozenset({source.job_id}))

    result, report = retrieve_windows_with_report(
        case.store, case.index, replace(case.query, scope=scope), dense=case.dense
    )

    assert (result, report.mode, report.reason) == (windows, "dense", None)


def test_retrieve_dense_below_threshold_does_not_fall_back_to_lexical_hits(
    case: CourseCase,
) -> None:
    docs = [document(number=i) for i in range(2)]
    populate(vectors=case.vectors, passages=docs, values=[(0.0, 1.0)] * 2)

    result, report = retrieve_windows_with_report(
        case.store, case.index, case.query, dense=case.dense
    )

    assert retrieve_windows(case.store, case.index, case.query) == docs
    assert (result, report.mode, report.reason) == ([], "dense", None)
