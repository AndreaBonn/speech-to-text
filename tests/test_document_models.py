from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime

import pytest

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus

CREATED = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def _document(
    status: DocumentStatus = DocumentStatus.UPLOADING,
    error: str | None = None,
    pages: int | None = None,
) -> CourseDocument:
    return CourseDocument(
        id="doc-id",
        course_id="course-id",
        filename="../../manuale.pdf",
        kind=DocumentKind.PDF,
        size=7,
        sha256="abc",
        status=status,
        error=error,
        pages=pages,
        created_at=CREATED,
    )


def test_course_document_metadata_is_frozen() -> None:
    record = _document()
    assert asdict(record) == {
        "id": "doc-id",
        "course_id": "course-id",
        "filename": "../../manuale.pdf",
        "kind": "pdf",
        "size": 7,
        "sha256": "abc",
        "status": "uploading",
        "error": None,
        "pages": None,
        "created_at": CREATED,
    }
    attribute = "filename"
    with pytest.raises(FrozenInstanceError):
        setattr(record, attribute, "modified.pdf")


@pytest.mark.parametrize(
    ("status", "error", "pages"),
    [
        (DocumentStatus.UPLOADING, None, None),
        (DocumentStatus.EXTRACTING, None, None),
        (DocumentStatus.READY, None, 3),
        (DocumentStatus.READY_NO_TEXT, None, 2),
        (DocumentStatus.FAILED, "EXTRACTION_TIMEOUT", None),
    ],
)
def test_course_document_accepts_consistent_states(
    status: DocumentStatus, error: str | None, pages: int | None
) -> None:
    assert _document(status=status, error=error, pages=pages).status == status


@pytest.mark.parametrize(
    ("status", "error", "pages"),
    [
        (DocumentStatus.READY, "boom", 3),
        (DocumentStatus.FAILED, None, None),
        (DocumentStatus.UPLOADING, None, 5),
        (DocumentStatus.READY, None, None),
        (DocumentStatus.READY, None, -1),
    ],
)
def test_course_document_rejects_inconsistent_states(
    status: DocumentStatus, error: str | None, pages: int | None
) -> None:
    with pytest.raises(ValueError):
        _document(status=status, error=error, pages=pages)


def test_course_document_rejects_negative_size() -> None:
    with pytest.raises(ValueError):
        replace(_document(), size=-1)


def test_document_status_values_match_persisted_contract() -> None:
    assert [status.value for status in DocumentStatus] == [
        "uploading",
        "extracting",
        "ready",
        "ready_no_text",
        "failed",
    ]
    assert [kind.value for kind in DocumentKind] == ["pdf", "docx", "pptx", "txt", "md"]
