import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from sbobina.document_passages import DocumentPassage
from sbobina.search_text import SnippetPart
from sbobina.web.document_index import DocumentScope, DocumentState
from sbobina.web.search_index import SearchIndex, open_index

STATE = DocumentState(course_id="course-1", text_mtime_ns=111, text_size=222)
PASSAGE = DocumentPassage(
    passage_id="doc1:p1:c0", page=1, chunk=0, text="la causa del contratto è illecita"
)


@pytest.fixture
def index(tmp_path: Path) -> Iterator[SearchIndex]:
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        yield index


def test_open_index_v1_rebuilds_for_document_search(tmp_path: Path) -> None:
    path = tmp_path / "search.sqlite3"
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(
            "CREATE TABLE lectures (job_id TEXT PRIMARY KEY, variant TEXT NOT NULL, "
            "path_mtime_ns INTEGER NOT NULL, path_size INTEGER NOT NULL, "
            "indexed_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE passages USING fts5("
            "text, job_id UNINDEXED, segment_index UNINDEXED, start UNINDEXED, "
            "tokenize='unicode61 remove_diacritics 2', prefix='3')"
        )
        connection.execute(
            "INSERT INTO lectures VALUES ('legacy', 'original', 1, 10, '2026-01-01')"
        )
        connection.execute("INSERT INTO passages VALUES ('causa', 'legacy', 0, 0.0)")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    with closing(open_index(path=path)) as index:
        index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
        page = index.search_documents(
            match='"causa"*', course_id="course-1", limit=10, offset=0
        )
        assert [hit.doc_id for hit in page.items] == ["doc1"]
    with closing(sqlite3.connect(database=path)) as connection:
        assert connection.execute("SELECT job_id FROM lectures").fetchall() == []
        assert connection.execute("SELECT text FROM passages").fetchall() == []
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)


def test_search_documents_returns_page_and_chunk_with_highlight(
    index: SearchIndex,
) -> None:
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    page = index.search_documents(
        match='"contratt"*', course_id="course-1", limit=10, offset=0
    )
    assert page.total == 1
    hit = page.items[0]
    assert hit.doc_id == "doc1"
    assert hit.page == 1
    assert hit.chunk == 0
    assert hit.snippet == [
        SnippetPart(text="la causa del ", match=False),
        SnippetPart(text="contratto", match=True),
        SnippetPart(text=" è illecita", match=False),
    ]


def test_search_documents_is_scoped_to_course(index: SearchIndex) -> None:
    other = DocumentState(course_id="course-2", text_mtime_ns=1, text_size=1)
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    index.replace_document(doc_id="doc2", state=other, passages=[PASSAGE])
    page = index.search_documents(
        match='"causa"*', course_id="course-2", limit=10, offset=0
    )
    assert [hit.doc_id for hit in page.items] == ["doc2"]


def test_search_documents_without_course_id_searches_every_course(
    index: SearchIndex,
) -> None:
    other = DocumentState(course_id="course-2", text_mtime_ns=1, text_size=1)
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    index.replace_document(doc_id="doc2", state=other, passages=[PASSAGE])
    page = index.search_documents(match='"causa"*', course_id=None, limit=10, offset=0)
    assert {hit.doc_id for hit in page.items} == {"doc1", "doc2"}
    assert {hit.course_id for hit in page.items} == {"course-1", "course-2"}


def test_replace_document_is_persistent_and_has_no_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "search.sqlite3"
    updated = DocumentState(course_id="course-1", text_mtime_ns=999, text_size=333)
    with closing(open_index(path=path)) as index:
        index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
        index.replace_document(doc_id="doc1", state=updated, passages=[PASSAGE])
    with closing(open_index(path=path)) as index:
        assert index.indexed_documents() == {"doc1": updated}
        page = index.search_documents(
            match='"causa"*', course_id="course-1", limit=10, offset=0
        )
        assert page.total == 1


def test_remove_document_deletes_passages_and_state(index: SearchIndex) -> None:
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    index.remove_document(doc_id="doc1")
    assert index.indexed_documents() == {}
    page = index.search_documents(
        match='"causa"*', course_id="course-1", limit=10, offset=0
    )
    assert page.total == 0


def test_indexed_documents_empty_on_fresh_index(index: SearchIndex) -> None:
    assert index.indexed_documents() == {}
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    assert index.indexed_documents() == {"doc1": STATE}


def test_search_documents_returns_a_short_snippet_of_a_long_page(
    index: SearchIndex,
) -> None:
    filler = " ".join(f"parola{n}" for n in range(400))
    long_page = DocumentPassage(
        passage_id="doc1:p1:c0",
        page=1,
        chunk=0,
        text=f"{filler} vincolo di bilancio {filler}",
    )
    index.replace_document(doc_id="doc1", state=STATE, passages=[long_page])

    page = index.search_documents(
        match='"vincol"*', course_id="course-1", limit=10, offset=0
    )

    text = "".join(part.text for part in page.items[0].snippet)
    assert "vincolo" in text
    assert len(text.split()) <= 40


def test_course_document_passages_returns_every_passage_in_reading_order(
    index: SearchIndex,
) -> None:
    second_page = DocumentPassage(
        passage_id="doc1:p2:c0", page=2, chunk=0, text="altra pagina"
    )
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE, second_page])

    rows = index.course_document_passages(scope=DocumentScope(course_id="course-1"))

    assert [row.passage_id for row in rows] == ["doc1:p1:c0", "doc1:p2:c0"]
    assert rows[0].text == PASSAGE.text


def test_course_document_passages_is_scoped_to_course(index: SearchIndex) -> None:
    other = DocumentState(course_id="course-2", text_mtime_ns=1, text_size=1)
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    index.replace_document(doc_id="doc2", state=other, passages=[PASSAGE])

    rows = index.course_document_passages(scope=DocumentScope(course_id="course-1"))

    assert [row.doc_id for row in rows] == ["doc1"]


def test_course_document_passages_filters_to_selected_doc_ids(
    index: SearchIndex,
) -> None:
    other = DocumentPassage(passage_id="doc2:p1:c0", page=1, chunk=0, text="altro doc")
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    index.replace_document(doc_id="doc2", state=STATE, passages=[other])

    rows = index.course_document_passages(
        scope=DocumentScope(course_id="course-1", doc_ids=frozenset({"doc2"}))
    )

    assert [row.doc_id for row in rows] == ["doc2"]


def test_course_document_passages_empty_course_returns_nothing(
    index: SearchIndex,
) -> None:
    index.replace_document(doc_id="doc1", state=STATE, passages=[PASSAGE])
    assert (
        index.course_document_passages(scope=DocumentScope(course_id="nessuno")) == []
    )
    rows = index.course_document_passages(scope=DocumentScope(course_id="course-1"))
    assert [row.passage_id for row in rows] == [PASSAGE.passage_id]
