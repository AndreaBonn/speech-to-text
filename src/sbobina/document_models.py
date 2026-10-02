from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DocumentKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    MD = "md"


class DocumentStatus(StrEnum):
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    READY = "ready"
    READY_NO_TEXT = "ready_no_text"
    FAILED = "failed"


EXTRACTED_STATUSES = frozenset({DocumentStatus.READY, DocumentStatus.READY_NO_TEXT})


@dataclass(frozen=True)
class CourseDocument:
    id: str
    course_id: str
    filename: str
    kind: DocumentKind
    size: int
    sha256: str
    status: DocumentStatus
    error: str | None
    pages: int | None
    created_at: datetime

    def __post_init__(self) -> None:
        # Reject states no transition produces: an error outside FAILED, or a
        # page count before extraction has finished.
        if self.size < 0:
            raise ValueError("size must not be negative")
        if (self.error is not None) != (self.status is DocumentStatus.FAILED):
            raise ValueError(f"error is set only when failed, got {self.status}")
        has_pages = self.status in EXTRACTED_STATUSES
        if (self.pages is not None) != has_pages:
            raise ValueError(f"pages is set only after extraction, got {self.status}")
        if self.pages is not None and self.pages < 0:
            raise ValueError("pages must not be negative")
