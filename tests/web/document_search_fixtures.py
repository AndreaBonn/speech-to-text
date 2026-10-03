"""Course documents written straight to disk for search reconciliation tests."""

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
