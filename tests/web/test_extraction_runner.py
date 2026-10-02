import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from document_fixtures import write_pdf

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.web import document_store, extraction_runner

REAL_APPLY_MEMORY_LIMIT = extraction_runner._apply_memory_limit


@pytest.fixture(autouse=True)
def _record_memory_limit(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    # These tests run the child's entry point inside pytest: applying the real
    # RLIMIT_AS here would cap pytest itself for the rest of the session.
    applied: list[int] = []
    monkeypatch.setattr(
        extraction_runner,
        "_apply_memory_limit",
        lambda max_memory_mb: applied.append(max_memory_mb),
    )
    return applied


def _doc_dir(tmp_path: Path) -> Path:
    doc_dir = tmp_path / "course-1" / "documents" / "doc-1"
    doc_dir.mkdir(parents=True)
    document = CourseDocument(
        id="doc-1",
        course_id="course-1",
        filename="manual.pdf",
        kind=DocumentKind.PDF,
        size=10,
        sha256="a" * 64,
        status=DocumentStatus.EXTRACTING,
        error=None,
        pages=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    document_store.write_document(courses_dir=tmp_path, document=document)
    write_pdf(
        path=doc_dir / "original.pdf",
        texts=("First page of the manual", "Second page about physics"),
    )
    return doc_dir


def test_run_extraction_writes_text_json(tmp_path: Path) -> None:
    doc_dir = _doc_dir(tmp_path)
    extraction_runner.run_extraction(doc_dir=doc_dir, max_memory_mb=512)
    stored = document_store.read_text(doc_dir=doc_dir)
    assert tuple(page.text for page in stored.pages) == (
        "First page of the manual",
        "Second page about physics",
    )
    assert stored.status == DocumentStatus.READY


def test_run_extraction_applies_memory_limit_before_opening_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_dir = _doc_dir(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        extraction_runner,
        "_apply_memory_limit",
        lambda max_memory_mb: calls.append("limit"),
    )
    original_extract = extraction_runner.extract

    def spy_extract(path: Path, kind: DocumentKind) -> object:
        calls.append("extract")
        return original_extract(path=path, kind=kind)

    monkeypatch.setattr(extraction_runner, "extract", spy_extract)
    extraction_runner.run_extraction(doc_dir=doc_dir, max_memory_mb=512)
    assert calls == ["limit", "extract"]


@pytest.mark.skipif(
    sys.platform == "win32", reason="RLIMIT_AS does not exist on Windows"
)
def test_apply_memory_limit_sets_rlimit_as(monkeypatch: pytest.MonkeyPatch) -> None:
    import resource

    recorded: list[tuple[int, int]] = []
    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda which, limits: recorded.append((which, limits[0])),
    )
    REAL_APPLY_MEMORY_LIMIT(max_memory_mb=256)
    assert recorded == [(resource.RLIMIT_AS, 256 * 1024 * 1024)]


def test_main_rejects_wrong_argument_count() -> None:
    assert extraction_runner.main(["extract", "only-one-arg"]) == 2
    assert extraction_runner.main(["wrong-command", "a", "b"]) == 2


def test_main_returns_zero_on_success(tmp_path: Path) -> None:
    doc_dir = _doc_dir(tmp_path)
    assert extraction_runner.main(["extract", str(doc_dir), "512"]) == 0
    assert document_store.read_text(doc_dir=doc_dir).status == DocumentStatus.READY


def test_main_returns_one_when_extraction_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_dir = tmp_path / "course-1" / "documents" / "missing"
    doc_dir.mkdir(parents=True)
    assert extraction_runner.main(["extract", str(doc_dir), "512"]) == 1
