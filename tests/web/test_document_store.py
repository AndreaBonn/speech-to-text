from datetime import UTC, datetime
from pathlib import Path

import pytest

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.web import document_store
from sbobina.web.errors import NotFoundError

CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _document(
    course_id: str = "course-1",
    doc_id: str = "doc-1",
    status: DocumentStatus = DocumentStatus.UPLOADING,
    error: str | None = None,
    pages: int | None = None,
) -> CourseDocument:
    return CourseDocument(
        id=doc_id,
        course_id=course_id,
        filename="manual.pdf",
        kind=DocumentKind.PDF,
        size=1024,
        sha256="a" * 64,
        status=status,
        error=error,
        pages=pages,
        created_at=CREATED_AT,
    )


def test_write_and_read_document_roundtrip(tmp_path: Path) -> None:
    document = _document()
    document_store.write_document(courses_dir=tmp_path, document=document)
    read_back = document_store.read_document(
        courses_dir=tmp_path, course_id="course-1", doc_id="doc-1"
    )
    assert read_back == document


def test_read_document_missing_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        document_store.read_document(
            courses_dir=tmp_path, course_id="course-1", doc_id="missing"
        )


def test_mark_extracting_sets_status(tmp_path: Path) -> None:
    document_store.write_document(courses_dir=tmp_path, document=_document())
    updated = document_store.mark_extracting(
        courses_dir=tmp_path, course_id="course-1", doc_id="doc-1"
    )
    assert updated.status == DocumentStatus.EXTRACTING
    assert (
        document_store.read_document(
            courses_dir=tmp_path, course_id="course-1", doc_id="doc-1"
        ).status
        == DocumentStatus.EXTRACTING
    )


def test_mark_extracted_sets_status_and_page_count(tmp_path: Path) -> None:
    document_store.write_document(
        courses_dir=tmp_path, document=_document(status=DocumentStatus.EXTRACTING)
    )
    result = document_store.StoredText(
        pages=(Page(text="a", no_text=False), Page(text="b", no_text=False)),
        status=DocumentStatus.READY,
        encoding=None,
    )
    updated = document_store.mark_extracted(
        courses_dir=tmp_path, course_id="course-1", doc_id="doc-1", result=result
    )
    assert updated.status == DocumentStatus.READY
    assert updated.pages == 2


def test_mark_failed_sets_error_code(tmp_path: Path) -> None:
    document_store.write_document(
        courses_dir=tmp_path, document=_document(status=DocumentStatus.EXTRACTING)
    )
    updated = document_store.mark_failed(
        courses_dir=tmp_path,
        course_id="course-1",
        doc_id="doc-1",
        code="EXTRACTION_TIMEOUT",
    )
    assert updated.status == DocumentStatus.FAILED
    assert updated.error == "EXTRACTION_TIMEOUT"


def test_iter_documents_scopes_to_one_course(tmp_path: Path) -> None:
    document_store.write_document(courses_dir=tmp_path, document=_document())
    document_store.write_document(
        courses_dir=tmp_path, document=_document(doc_id="doc-2")
    )
    document_store.write_document(
        courses_dir=tmp_path, document=_document(course_id="course-2", doc_id="doc-3")
    )
    ids = {
        document.id
        for document in document_store.iter_documents(
            courses_dir=tmp_path, course_id="course-1"
        )
    }
    assert ids == {"doc-1", "doc-2"}


def test_iter_extracting_documents_finds_orphans_across_courses(
    tmp_path: Path,
) -> None:
    document_store.write_document(
        courses_dir=tmp_path,
        document=_document(
            course_id="course-1", doc_id="ready", status=DocumentStatus.READY, pages=3
        ),
    )
    document_store.write_document(
        courses_dir=tmp_path,
        document=_document(
            course_id="course-2", doc_id="orphan", status=DocumentStatus.EXTRACTING
        ),
    )
    orphans = list(document_store.iter_extracting_documents(courses_dir=tmp_path))
    assert [document.id for document in orphans] == ["orphan"]


def test_write_and_read_text_roundtrip(tmp_path: Path) -> None:
    doc_dir = tmp_path / "course-1" / "documents" / "doc-1"
    doc_dir.mkdir(parents=True)
    extracted = ExtractedText(
        pages=(Page(text="Hello", no_text=False),),
        status=DocumentStatus.READY,
        encoding="utf-8",
    )
    document_store.write_text(doc_dir=doc_dir, extracted=extracted)
    stored = document_store.read_text(doc_dir=doc_dir)
    assert stored.pages == extracted.pages
    assert stored.status == extracted.status
    assert stored.encoding == extracted.encoding


def test_write_and_read_text_roundtrip_preserves_ocr_flag(tmp_path: Path) -> None:
    doc_dir = tmp_path / "course-1" / "documents" / "doc-1"
    doc_dir.mkdir(parents=True)
    extracted = ExtractedText(
        pages=(Page(text="Letta con OCR", no_text=False, ocr=True),),
        status=DocumentStatus.READY,
        encoding=None,
    )
    document_store.write_text(doc_dir=doc_dir, extracted=extracted)
    stored = document_store.read_text(doc_dir=doc_dir)
    assert stored.pages == extracted.pages
    assert stored.pages[0].ocr is True


def test_read_text_without_ocr_field_defaults_to_false(tmp_path: Path) -> None:
    doc_dir = tmp_path / "course-1" / "documents" / "doc-1"
    doc_dir.mkdir(parents=True)
    (doc_dir / document_store.TEXT_FILENAME).write_text(
        '{"pages": [{"text": "Hello", "no_text": false}], '
        '"status": "ready", "encoding": "utf-8"}',
        encoding="utf-8",
    )
    stored = document_store.read_text(doc_dir=doc_dir)
    assert stored.pages[0].ocr is False


def test_original_path_uses_kind_extension(tmp_path: Path) -> None:
    assert (
        document_store.original_path(doc_dir=tmp_path, kind=DocumentKind.PPTX)
        == tmp_path / "original.pptx"
    )
