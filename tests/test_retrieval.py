from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from sbobina.document_passages import DocumentPassage
from sbobina.rank_fusion import fuse_by_rank
from sbobina.retrieval import (
    DocumentSource,
    LectureSource,
    RetrievalScope,
    RetrievedPassage,
    question_to_fts,
    retrieve,
)
from sbobina.search_text import Passage
from sbobina.web.document_index import DocumentState
from sbobina.web.search_index import LectureState, SearchIndex, open_index

STATE = LectureState(variant="original", path_mtime_ns=1, path_size=1)
DOC_STATE_A = DocumentState(course_id="course-a", text_mtime_ns=1, text_size=1)
DOC_STATE_B = DocumentState(course_id="course-b", text_mtime_ns=1, text_size=1)


@pytest.fixture
def index(tmp_path: Path) -> Iterator[SearchIndex]:
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        yield index


# --- question_to_fts --------------------------------------------------------


def test_question_to_fts_drops_italian_stopwords_and_stems_content_words() -> None:
    assert question_to_fts("cos'è la causa del contratto?") == '"caus"* OR "contratt"*'


def test_question_to_fts_returns_none_when_only_stopwords_remain() -> None:
    assert question_to_fts("che cos'è") is None


def test_question_to_fts_returns_none_for_empty_question() -> None:
    assert question_to_fts("") is None


def test_question_to_fts_never_leaks_fts_operators(index: SearchIndex) -> None:
    """Quoting makes every operator in the raw question inert, never crashes."""
    index.replace_lecture(
        job_id="job",
        state=STATE,
        passages=[
            Passage(
                segment_index=0, start=0.0, text="il teorema di Rolle vale per funzioni"
            )
        ],
    )
    match = question_to_fts('teorema "NEAR(rolle)" - valore* :bar')
    assert match is not None
    for operator in ('"NEAR(', "- ", "*)", ":bar"):
        assert operator not in match
    # Must not raise despite the raw operators, and must still find the real match.
    page = index.search(match=match, job_ids=None, limit=10, offset=0)
    assert page.total == 1


# --- retrieve ----------------------------------------------------------------


def _passage(text: str, segment_index: int = 0) -> Passage:
    return Passage(segment_index=segment_index, start=float(segment_index), text=text)


def _doc_passage(
    passage_id: str, text: str, page: int = 1, chunk: int = 0
) -> DocumentPassage:
    return DocumentPassage(passage_id=passage_id, page=page, chunk=chunk, text=text)


def test_retrieve_returns_both_lecture_and_document_passages(
    index: SearchIndex,
) -> None:
    index.replace_lecture(
        job_id="lecture-1",
        state=STATE,
        passages=[_passage("il contratto è nullo per causa illecita")],
    )
    index.replace_document(
        doc_id="doc-1",
        state=DOC_STATE_A,
        passages=[_doc_passage("doc-1:p1:c0", "la causa del contratto è discussa qui")],
    )
    scope = RetrievalScope(course_id="course-a", job_ids=frozenset({"lecture-1"}))
    results = retrieve(
        index=index,
        scope=scope,
        question="qual è la causa del contratto?",
        budget_words=1000,
    )
    sources = {type(r.source) for r in results}
    assert sources == {LectureSource, DocumentSource}


def test_retrieve_course_scope_returns_only_its_lecture_and_document(
    index: SearchIndex,
) -> None:
    index.replace_lecture(
        job_id="lecture-a", state=STATE, passages=[_passage("causa del contratto")]
    )
    index.replace_lecture(
        job_id="lecture-b", state=STATE, passages=[_passage("causa del contratto")]
    )
    index.replace_document(
        doc_id="doc-a",
        state=DOC_STATE_A,
        passages=[_doc_passage("doc-a:p1:c0", "causa del contratto")],
    )
    index.replace_document(
        doc_id="doc-b",
        state=DOC_STATE_B,
        passages=[_doc_passage("doc-b:p1:c0", "causa del contratto")],
    )
    scope = RetrievalScope(course_id="course-a", job_ids=frozenset({"lecture-a"}))
    results = retrieve(
        index=index, scope=scope, question="causa del contratto", budget_words=1000
    )
    assert {
        result.source.job_id
        if isinstance(result.source, LectureSource)
        else result.source.doc_id
        for result in results
    } == {"lecture-a", "doc-a"}


@pytest.mark.parametrize(("budget_words", "expected_count"), [(25, 1), (1000, 3)])
def test_retrieve_word_budget_keeps_exactly_fitting_passages(
    index: SearchIndex, budget_words: int, expected_count: int
) -> None:
    index.replace_document(
        doc_id="doc-1",
        state=DOC_STATE_A,
        passages=[
            _doc_passage("doc-1:p1:c0", "causa " * 20, page=1, chunk=0),
            _doc_passage("doc-1:p2:c0", "causa " * 20, page=2, chunk=0),
            _doc_passage("doc-1:p3:c0", "causa " * 20, page=3, chunk=0),
        ],
    )
    scope = RetrievalScope(course_id="course-a", job_ids=frozenset())
    results = retrieve(
        index=index, scope=scope, question="causa", budget_words=budget_words
    )

    assert len(results) == expected_count
    assert sum(len(result.text.split()) for result in results) == 20 * expected_count


def test_retrieve_scope_selected_narrows_to_chosen_sources(index: SearchIndex) -> None:
    index.replace_lecture(
        job_id="lecture-a", state=STATE, passages=[_passage("causa del contratto")]
    )
    index.replace_lecture(
        job_id="lecture-b", state=STATE, passages=[_passage("causa del contratto")]
    )
    scope = RetrievalScope(
        course_id="course-a",
        job_ids=frozenset({"lecture-a", "lecture-b"}),
        selected=frozenset({"lecture-a"}),
    )
    results = retrieve(index=index, scope=scope, question="causa", budget_words=1000)
    assert {
        r.source.job_id for r in results if isinstance(r.source, LectureSource)
    } == {"lecture-a"}


def test_retrieve_returns_empty_when_question_has_no_content_words(
    index: SearchIndex,
) -> None:
    index.replace_lecture(
        job_id="lecture-a", state=STATE, passages=[_passage("causa del contratto")]
    )
    scope = RetrievalScope(course_id="course-a", job_ids=frozenset({"lecture-a"}))
    assert (
        retrieve(index=index, scope=scope, question="che cos'è", budget_words=1000)
        == []
    )


def _ranked(name: str) -> RetrievedPassage:
    return RetrievedPassage(
        text=name,
        source=DocumentSource(doc_id=name, page=1, chunk=0),
        passage_id=name,
    )


def test_fuse_by_rank_interleaves_sources_whatever_their_raw_scores() -> None:
    # bm25 of two FTS tables comes from different corpus statistics: documents
    # scoring -50 against lectures at -1 must not push every lecture out.
    lectures = [(-1.0, _ranked("L1")), (-0.9, _ranked("L2"))]
    documents = [(-50.0, _ranked("D1")), (-49.0, _ranked("D2"))]

    fused = fuse_by_rank(rankings=[lectures, documents])

    assert {fused[0].passage_id, fused[1].passage_id} == {"L1", "D1"}
    assert {fused[2].passage_id, fused[3].passage_id} == {"L2", "D2"}
    assert [item[1].passage_id for item in documents] == ["D1", "D2"]


def test_retrieve_selected_document_survives_more_relevant_documents(
    index: SearchIndex,
) -> None:
    # 60 passages that match better than the selected one: a filter applied
    # after the candidate LIMIT would drop the selected document entirely.
    index.replace_document(
        doc_id="manuale",
        state=DOC_STATE_A,
        passages=[
            _doc_passage(
                passage_id=f"manuale:p{n}:c0", text="causa causa causa", page=n
            )
            for n in range(1, 61)
        ],
    )
    index.replace_document(
        doc_id="appunti",
        state=DOC_STATE_A,
        passages=[
            _doc_passage(
                passage_id="appunti:p1:c0",
                text="la causa del contratto spiegata in poche parole sparse qui",
            )
        ],
    )
    scope = RetrievalScope(
        course_id="course-a", job_ids=frozenset(), selected=frozenset({"appunti"})
    )

    passages = retrieve(index=index, scope=scope, question="causa", budget_words=500)

    assert [passage.passage_id for passage in passages] == ["appunti:p1:c0"]


def test_question_to_fts_drops_words_that_stem_to_nothing() -> None:
    # Stemming strips final vowels: an all-vowel word leaves no term at all.
    assert question_to_fts("aaaaaa") is None
    assert question_to_fts("aaaaaa diritto") == '"diritt"*'
