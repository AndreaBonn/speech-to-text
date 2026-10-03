"""Shared setup for the server-rendered page tests."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import JsonValue

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.web import pages
from sbobina.web.document_store import write_document


def write_course_document(
    tmp_path: Path, filename: str, status: DocumentStatus = DocumentStatus.READY
) -> tuple[str, str]:
    """Seed a registered course with one document, bypassing the upload API."""
    courses_dir = tmp_path / "courses"
    course = get_or_create(courses_dir=courses_dir, key="fisica", label="Fisica")
    doc_id = "doc-1"
    doc_dir = courses_dir / course.id / "documents" / doc_id
    doc_dir.mkdir(parents=True)
    extracted = status in (DocumentStatus.READY, DocumentStatus.READY_NO_TEXT)
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course.id,
            filename=filename,
            kind=DocumentKind.PDF,
            size=1,
            sha256="0" * 64,
            status=status,
            error="EXTRACTION_FAILED" if status == DocumentStatus.FAILED else None,
            pages=1 if extracted else None,
            created_at=datetime.now(tz=UTC),
        ),
    )
    return course.key, doc_id


BASE_URL = "http://127.0.0.1:8765"
FORM_FIELD_NAMES = (
    'name="file"',
    'name="subject"',
    'name="correct"',
    'name="ollama_model"',
    'name="whisper_model"',
    'name="beam_size"',
    'name="vad_filter"',
    'name="condition_on_previous_text"',
    'name="uncertain_threshold"',
)


OLLAMA_READY: dict[str, JsonValue] = {
    "status": "ready",
    "message": "Ollama è pronto.",
    "models": [{"model": "qwen3.5:2b", "size": 1, "parameter_size": "2B"}],
}
WHISPER_MODELS: list[dict[str, JsonValue]] = [
    {
        "name": "large-v3-turbo",
        "downloaded": True,
        "recommended_gpu": False,
        "recommended_cpu": True,
    },
    {
        "name": "medium",
        "downloaded": False,
        "recommended_gpu": False,
        "recommended_cpu": False,
    },
]


@pytest.fixture(autouse=True)
def _models() -> object:
    """Keep the index page off the real Ollama server and Hugging Face cache."""
    with (
        patch.object(pages, "ollama_status", return_value=OLLAMA_READY),
        patch.object(pages, "list_whisper_models", return_value=WHISPER_MODELS),
    ):
        yield
