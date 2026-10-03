"""A registered course holding one scanned PDF: no page has native text."""

from datetime import UTC, datetime
from pathlib import Path

from document_fixtures import write_pdf

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.web.document_store import (
    document_dir,
    original_path,
    write_document,
    write_text,
)

COURSE_KEY = "fisica"
DOC_ID = "4b3c2d1e-0000-4000-8000-000000000001"


def add_scanned_document(
    courses_dir: Path, status: DocumentStatus = DocumentStatus.READY_NO_TEXT
) -> tuple[str, Path]:
    """Course id and document dir of a two-page PDF without native text."""
    course = get_or_create(courses_dir=courses_dir, key=COURSE_KEY, label="Fisica")
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course.id, doc_id=DOC_ID)
    doc_dir.mkdir(parents=True)
    write_pdf(
        path=original_path(doc_dir=doc_dir, kind=DocumentKind.PDF),
        texts=("pagina con testo", "pagina scansionata"),
    )
    pages = (
        Page(text="", no_text=True),
        Page(text="", no_text=True),
    )
    write_text(doc_dir=doc_dir, extracted=ExtractedText(pages=pages, status=status))
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=DOC_ID,
            course_id=course.id,
            filename="scansione.pdf",
            kind=DocumentKind.PDF,
            size=10,
            sha256="b" * 64,
            status=status,
            error=None,
            pages=2,
            created_at=datetime.now(UTC),
        ),
    )
    return course.id, doc_dir
