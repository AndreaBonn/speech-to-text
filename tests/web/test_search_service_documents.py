import os
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.web.document_store import (
    document_dir,
    mark_extracted,
    read_text,
    write_document,
    write_text,
)
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import open_index
from sbobina.web.search_service import (
    DocumentSearchQuery,
    reconcile,
    search_documents,
    search_session,
)


def write_ready_document(
    courses_dir: Path,
    course_id: str,
    doc_id: str,
    pages: list[Page],
    status: DocumentStatus = DocumentStatus.READY,
) -> Path:
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course_id,
            filename="manuale.pdf",
            kind=DocumentKind.PDF,
            size=10,
            sha256="0" * 64,
            status=DocumentStatus.EXTRACTING,
            error=None,
            pages=None,
            created_at=datetime.now(tz=UTC),
        ),
    )
    write_text(
        doc_dir=doc_dir, extracted=ExtractedText(pages=tuple(pages), status=status)
    )
    mark_extracted(
        courses_dir=courses_dir,
        course_id=course_id,
        doc_id=doc_id,
        result=read_text(doc_dir=doc_dir),
    )
    return doc_dir


def write_failed_document(courses_dir: Path, course_id: str, doc_id: str) -> Path:
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course_id,
            filename="manuale.pdf",
            kind=DocumentKind.PDF,
            size=10,
            sha256="0" * 64,
            status=DocumentStatus.FAILED,
            error="CORRUPT",
            pages=None,
            created_at=datetime.now(tz=UTC),
        ),
    )
    return doc_dir


@pytest.fixture
def courses_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "courses"


def test_reconcile_finds_new_ready_document(tmp_path: Path, courses_dir: Path) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="la causa del contratto", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        page = index.search_documents(
            match='"contratt"*', course_id="course-1", limit=10, offset=0
        )
        assert page.total == 1
        assert page.items[0].doc_id == "doc1"
        assert page.items[0].page == 1


def test_reconcile_skips_ready_no_text_document(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="", no_text=True)],
        status=DocumentStatus.READY_NO_TEXT,
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 0
        assert index.indexed_documents() == {}


def test_reconcile_skips_document_not_ready(tmp_path: Path, courses_dir: Path) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_failed_document(courses_dir=courses_dir, course_id="course-1", doc_id="doc1")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 0
        assert index.indexed_documents() == {}


def test_reconcile_unchanged_document_is_not_reindexed(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="causa", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        assert reconcile(store=store, index=index) == 0


def test_reconcile_reindexes_when_text_json_changes(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    doc_dir = write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="prima", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        previous = (doc_dir / "text.json").stat()
        write_text(
            doc_dir=doc_dir,
            extracted=ExtractedText(
                pages=(Page(text="dopo", no_text=False),), status=DocumentStatus.READY
            ),
        )
        stamp = previous.st_mtime_ns + 1
        os.utime(doc_dir / "text.json", ns=(stamp, stamp))
        assert reconcile(store=store, index=index) == 1
        after = index.search_documents(
            match='"dopo"*', course_id="course-1", limit=10, offset=0
        )
        assert after.total == 1
        before = index.search_documents(
            match='"prima"*', course_id="course-1", limit=10, offset=0
        )
        assert before.total == 0


def test_reconcile_removes_document_deleted_from_disk(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    doc_dir = write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="causa", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        import shutil

        shutil.rmtree(doc_dir)
        assert reconcile(store=store, index=index) == 0
        assert index.indexed_documents() == {}


def test_reconcile_removes_document_no_longer_ready(
    tmp_path: Path, courses_dir: Path
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="doc1",
        pages=[Page(text="causa", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        write_text(
            doc_dir=document_dir(
                courses_dir=courses_dir, course_id="course-1", doc_id="doc1"
            ),
            extracted=ExtractedText(pages=(), status=DocumentStatus.READY_NO_TEXT),
        )
        mark_extracted(
            courses_dir=courses_dir,
            course_id="course-1",
            doc_id="doc1",
            result=read_text(
                doc_dir=document_dir(
                    courses_dir=courses_dir, course_id="course-1", doc_id="doc1"
                )
            ),
        )
        assert reconcile(store=store, index=index) == 0
        assert index.indexed_documents() == {}


def test_reconcile_skips_unreadable_text_json_and_keeps_others(
    tmp_path: Path, courses_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = JobStore(data_dir=tmp_path / "data")
    write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="good",
        pages=[Page(text="contratto", no_text=False)],
    )
    bad_dir = write_ready_document(
        courses_dir=courses_dir,
        course_id="course-1",
        doc_id="bad",
        pages=[Page(text="causa", no_text=False)],
    )
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 2
        (bad_dir / "text.json").write_text("{not json", encoding="utf-8")
        assert reconcile(store=store, index=index) == 0
        good = index.search_documents(
            match='"contratt"*', course_id="course-1", limit=10, offset=0
        )
        assert good.total == 1
        kept = index.search_documents(
            match='"causa"*', course_id="course-1", limit=10, offset=0
        )
        assert kept.total == 1
        assert "bad" in caplog.text


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
