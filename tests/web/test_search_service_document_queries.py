from pathlib import Path

from document_search_fixtures import (
    courses_dir,
    write_ready_document,
)

from sbobina.extracted_text import Page
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import (
    DocumentSearchQuery,
    search_documents,
    search_session,
)

__all__ = ["courses_dir"]


def test_search_session_reconciles_documents_too(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    path = tmp_path / "search.sqlite3"
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="causa", no_text=False)],
    )
    with search_session(store=store, path=path) as index:
        page = index.search_documents(
            match='"causa"*', course_id="course-1", limit=10, offset=0
        )
        assert page.total == 1


def test_search_documents_reconciles_before_querying(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    path = tmp_path / "search.sqlite3"
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="la causa del contratto", no_text=False)],
    )
    page = search_documents(
        store=store,
        path=path,
        query=DocumentSearchQuery(
            match='"causa"*', course_id="course-1", limit=10, offset=0
        ),
    )
    assert page.total == 1
    assert page.items[0].doc_id == "doc1"


def test_search_documents_without_course_id_covers_every_course(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    path = tmp_path / "search.sqlite3"
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="causa", no_text=False)],
    )
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-2",
        doc_id="doc2",
        pages=[Page(text="causa", no_text=False)],
    )
    page = search_documents(
        store=store,
        path=path,
        query=DocumentSearchQuery(match='"causa"*', course_id=None, limit=10, offset=0),
    )
    assert {item.doc_id for item in page.items} == {"doc1", "doc2"}
