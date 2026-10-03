from contextlib import closing
from pathlib import Path

from sbobina.course_registry import get_or_create
from sbobina.document_passages import DocumentPassage
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.retrieval import DocumentSource, LectureSource, RetrievalScope
from sbobina.search_text import Passage
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.course_retrieval import (
    WindowedQuery,
    course_scope,
    retrieve_windows,
    sample_course,
)
from sbobina.web.document_index import DocumentState
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import LectureState, open_index


def test_course_scope_collects_lectures_by_effective_course(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    explicit = store.create(config=JobConfig(subject="Fisica"))
    store.write_meta(job_id=str(explicit.id), meta=LectureMeta(course="Analisi 1"))
    fallback = store.create(config=JobConfig(subject="Analisi 1"))
    other = store.create(config=JobConfig(subject="Chimica"))

    scope = course_scope(store=store, key="analisi 1")

    assert scope.job_ids == {str(explicit.id), str(fallback.id)}
    assert str(other.id) not in scope.job_ids


def test_course_scope_carries_the_registry_id_for_document_search(
    tmp_path: Path,
) -> None:
    # Regression: lectures were matched against the registry uuid instead of
    # the course key, so a registered course never retrieved its lectures.
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Diritto"))
    course = get_or_create(
        courses_dir=store.courses_dir, key="diritto", label="Diritto"
    )

    scope = course_scope(store=store, key="diritto")

    assert scope.course_id == course.id
    assert scope.job_ids == {str(lecture.id)}


def test_course_scope_is_empty_for_unknown_course(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    store.create(config=JobConfig(subject="Fisica"))

    scope = course_scope(store=store, key="matematica")

    assert scope.job_ids == frozenset()


def _write_lecture(store: JobStore, job_id: str) -> None:
    """60 segments of 20 words, segment 30 a short 12-word match on 'contratto'."""
    segments = [
        Segment(
            start=float(i),
            end=float(i) + 1,
            words=(
                Word(
                    start=float(i),
                    end=float(i) + 1,
                    text="parola " * 20,
                    probability=0.99,
                ),
            ),
        )
        for i in range(60)
    ]
    segments[30] = Segment(
        start=30.0,
        end=31.0,
        words=(Word(start=30.0, end=31.0, text="contratto " * 12, probability=0.99),),
    )
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=60.0,
        segments=tuple(segments),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )


def test_retrieve_windows_expands_lecture_hit_beyond_raw_segment(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    job_id = str(record.id)
    _write_lecture(store=store, job_id=job_id)

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        index.replace_lecture(
            job_id=job_id,
            state=LectureState(variant="original", path_mtime_ns=1, path_size=1),
            passages=[Passage(segment_index=30, start=30.0, text="contratto " * 12)],
        )
        scope = RetrievalScope(course_id="fisica", job_ids=frozenset({job_id}))
        windows = retrieve_windows(
            store=store,
            index=index,
            query=WindowedQuery(scope=scope, question="contratto", budget_words=1000),
        )

    assert len(windows) == 1
    assert len(windows[0].text.split()) > 12
    assert windows[0].source == LectureSource(
        job_id=job_id, segment_index=30, start=30.0
    )


def test_retrieve_windows_cuts_budget_on_expanded_window_not_raw_segment(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    job_id = str(record.id)
    _write_lecture(store=store, job_id=job_id)

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        index.replace_lecture(
            job_id=job_id,
            state=LectureState(variant="original", path_mtime_ns=1, path_size=1),
            passages=[Passage(segment_index=30, start=30.0, text="contratto " * 12)],
        )
        scope = RetrievalScope(course_id="fisica", job_ids=frozenset({job_id}))
        # The raw segment (12 words) fits a 20-word budget; its expanded
        # ~250-word window does not: the cut must see the window, not the
        # segment, or this would wrongly return it.
        windows = retrieve_windows(
            store=store,
            index=index,
            query=WindowedQuery(scope=scope, question="contratto", budget_words=20),
        )

    assert windows == []


def _write_plain_lecture(
    store: JobStore, job_id: str, segment_count: int, words_per_segment: int
) -> None:
    """A lecture with uniform segments, for deterministic windowing in sampling."""
    segments = [
        Segment(
            start=float(i),
            end=float(i) + 1,
            words=(
                Word(
                    start=float(i),
                    end=float(i) + 1,
                    text="parola " * words_per_segment,
                    probability=0.99,
                ),
            ),
        )
        for i in range(segment_count)
    ]
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=float(segment_count),
        segments=tuple(segments),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )


def test_sample_course_covers_every_document_when_topic_is_empty(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    course = get_or_create(courses_dir=store.courses_dir, key="corso", label="Corso")

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        state = DocumentState(course_id=course.id, text_mtime_ns=1, text_size=1)
        index.replace_document(
            doc_id="doc1",
            state=state,
            passages=[
                DocumentPassage(
                    passage_id="doc1:p1:c0", page=1, chunk=0, text="alfa beta"
                )
            ],
        )
        index.replace_document(
            doc_id="doc2",
            state=state,
            passages=[
                DocumentPassage(
                    passage_id="doc2:p1:c0", page=1, chunk=0, text="gamma delta"
                )
            ],
        )
        scope = RetrievalScope(course_id=course.id, job_ids=frozenset())

        sampled = sample_course(store=store, index=index, scope=scope, budget_words=100)

    doc_ids = {
        source.doc_id
        for source in (passage.source for passage in sampled)
        if isinstance(source, DocumentSource)
    }
    assert doc_ids == {"doc1", "doc2"}


def test_sample_course_windows_a_whole_lecture_without_a_question(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))
    job_id = str(record.id)
    _write_plain_lecture(
        store=store, job_id=job_id, segment_count=60, words_per_segment=20
    )

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        scope = RetrievalScope(course_id="fisica", job_ids=frozenset({job_id}))
        sampled = sample_course(
            store=store, index=index, scope=scope, budget_words=10_000
        )

    assert len(sampled) > 1
    assert all(
        isinstance(passage.source, LectureSource) and passage.source.job_id == job_id
        for passage in sampled
    )
    assert sum(len(passage.text.split()) for passage in sampled) == 1200


def test_sample_course_respects_selected_scope(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    course = get_or_create(courses_dir=store.courses_dir, key="corso", label="Corso")

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        state = DocumentState(course_id=course.id, text_mtime_ns=1, text_size=1)
        index.replace_document(
            doc_id="doc1",
            state=state,
            passages=[
                DocumentPassage(passage_id="doc1:p1:c0", page=1, chunk=0, text="alfa")
            ],
        )
        index.replace_document(
            doc_id="doc2",
            state=state,
            passages=[
                DocumentPassage(passage_id="doc2:p1:c0", page=1, chunk=0, text="beta")
            ],
        )
        scope = RetrievalScope(
            course_id=course.id, job_ids=frozenset(), selected=frozenset({"doc1"})
        )

        sampled = sample_course(store=store, index=index, scope=scope, budget_words=100)

    doc_ids = {
        source.doc_id
        for source in (passage.source for passage in sampled)
        if isinstance(source, DocumentSource)
    }
    assert doc_ids == {"doc1"}


def test_sample_course_empty_course_returns_no_passages(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        scope = RetrievalScope(course_id="vuoto", job_ids=frozenset())
        sampled = sample_course(store=store, index=index, scope=scope, budget_words=100)

    assert sampled == []
