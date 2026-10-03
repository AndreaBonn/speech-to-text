import os
from contextlib import closing
from pathlib import Path

import pytest
from document_search_fixtures import (
    courses_dir,
    write_failed_document,
    write_ready_document,
)

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.web.document_store import (
    document_dir,
    mark_extracted,
    read_text,
    write_text,
)
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import open_index
from sbobina.web.search_service import (
    reconcile,
)

__all__ = ["courses_dir"]


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


def test_reconcile_does_not_index_document_with_unreadable_metadata(
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
    (bad_dir / "document.json").write_text("{not json", encoding="utf-8")

    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        replaced = reconcile(store=store, index=index)
        indexed = set(index.indexed_documents())

    assert (replaced, indexed) == (1, {"good"})
    assert "bad" in caplog.text
