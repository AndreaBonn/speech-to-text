"""Persistence for ``CourseDocument`` and its extracted text (T014/D4).

Layout: ``<courses_dir>/<course_id>/documents/<doc_id>/document.json`` (+
``original.<kind>``, written by the uploader, and ``text.json``, written by
the extraction runner on success).
"""

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.study_files import atomic_write_pair
from sbobina.web.errors import NotFoundError

DOCUMENT_FILENAME = "document.json"
TEXT_FILENAME = "text.json"
ORIGINAL_STEM = "original"


@dataclass(frozen=True)
class StoredText:
    pages: tuple[Page, ...]
    status: DocumentStatus
    encoding: str | None


def document_dir(courses_dir: Path, course_id: str, doc_id: str) -> Path:
    return courses_dir / course_id / "documents" / doc_id


def original_path(doc_dir: Path, kind: DocumentKind) -> Path:
    return doc_dir / f"{ORIGINAL_STEM}.{kind.value}"


def _document_to_json(document: CourseDocument) -> str:
    values = asdict(document) | {
        "kind": document.kind.value,
        "status": document.status.value,
        "created_at": document.created_at.isoformat(),
    }
    return json.dumps(values, ensure_ascii=False)


def _document_from_json(raw: dict[str, Any]) -> CourseDocument:
    return CourseDocument(
        id=str(raw["id"]),
        course_id=str(raw["course_id"]),
        filename=str(raw["filename"]),
        kind=DocumentKind(raw["kind"]),
        size=int(raw["size"]),
        sha256=str(raw["sha256"]),
        status=DocumentStatus(raw["status"]),
        error=None if raw["error"] is None else str(raw["error"]),
        pages=None if raw["pages"] is None else int(raw["pages"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
    )


def write_document(courses_dir: Path, document: CourseDocument) -> None:
    path = (
        document_dir(courses_dir, document.course_id, document.id) / DOCUMENT_FILENAME
    )
    atomic_write_pair(contents={path: _document_to_json(document=document)})


def read_document(courses_dir: Path, course_id: str, doc_id: str) -> CourseDocument:
    path = document_dir(courses_dir, course_id, doc_id) / DOCUMENT_FILENAME
    if not path.exists():
        raise NotFoundError(entity="Documento", id=doc_id)
    return _document_from_json(json.loads(path.read_text(encoding="utf-8")))


def read_document_in(doc_dir: Path) -> CourseDocument:
    """Read ``document.json`` by its own directory, for the extraction child."""
    return _document_from_json(
        json.loads((doc_dir / DOCUMENT_FILENAME).read_text(encoding="utf-8"))
    )


def iter_documents(courses_dir: Path, course_id: str) -> Iterator[CourseDocument]:
    for path in sorted(
        (courses_dir / course_id / "documents").glob(f"*/{DOCUMENT_FILENAME}")
    ):
        yield _document_from_json(json.loads(path.read_text(encoding="utf-8")))


def iter_extracting_documents(courses_dir: Path) -> Iterator[CourseDocument]:
    """Documents stuck in ``extracting`` across every course, for boot recovery."""
    for path in sorted(courses_dir.glob(f"*/documents/*/{DOCUMENT_FILENAME}")):
        document = _document_from_json(json.loads(path.read_text(encoding="utf-8")))
        if document.status is DocumentStatus.EXTRACTING:
            yield document


def write_text(doc_dir: Path, extracted: ExtractedText) -> None:
    values = {
        "pages": [
            {"text": page.text, "no_text": page.no_text, "ocr": page.ocr}
            for page in extracted.pages
        ],
        "status": extracted.status.value,
        "encoding": extracted.encoding,
    }
    atomic_write_pair(
        contents={doc_dir / TEXT_FILENAME: json.dumps(values, ensure_ascii=False)}
    )


def read_text(doc_dir: Path) -> StoredText:
    raw = json.loads((doc_dir / TEXT_FILENAME).read_text(encoding="utf-8"))
    pages = tuple(
        Page(
            text=str(item["text"]),
            no_text=bool(item["no_text"]),
            ocr=bool(item.get("ocr", False)),
        )
        for item in raw["pages"]
    )
    return StoredText(
        pages=pages,
        status=DocumentStatus(raw["status"]),
        encoding=None if raw["encoding"] is None else str(raw["encoding"]),
    )


def mark_extracting(courses_dir: Path, course_id: str, doc_id: str) -> CourseDocument:
    document = replace(
        read_document(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id),
        status=DocumentStatus.EXTRACTING,
    )
    write_document(courses_dir=courses_dir, document=document)
    return document


def mark_extracted(
    courses_dir: Path, course_id: str, doc_id: str, result: StoredText
) -> CourseDocument:
    document = replace(
        read_document(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id),
        status=result.status,
        pages=len(result.pages),
    )
    write_document(courses_dir=courses_dir, document=document)
    return document


def mark_failed(
    courses_dir: Path, course_id: str, doc_id: str, code: str
) -> CourseDocument:
    document = replace(
        read_document(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id),
        status=DocumentStatus.FAILED,
        error=code,
    )
    write_document(courses_dir=courses_dir, document=document)
    return document
