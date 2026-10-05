from pathlib import Path

import pytest
from ocr_fixtures import DOC_ID, add_scanned_document

from sbobina import llm_corrector
from sbobina.correction import CorrectorUnavailableError
from sbobina.document_models import DocumentStatus
from sbobina.settings import settings
from sbobina.web import ocr_runner
from sbobina.web.document_store import read_document, read_document_in, read_text
from sbobina.web.job_store import JobStore
from sbobina.web.ocr_runner import run_ocr
from sbobina.web.ocr_store import OcrStatus, create_ocr, load_ocr
from sbobina.web.search_service import search_session


def test_run_ocr_fills_the_scanned_pages_and_marks_the_document_ready(
    tmp_path: Path,
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=tmp_path)
    create_ocr(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)
    asked: list[int] = []

    def read_page(index: int) -> str:
        asked.append(index)
        return f"testo riconosciuto dalla pagina {index + 1}"

    run_ocr(document_dir=doc_dir, read_page=read_page)

    assert asked == [0, 1]
    pages = read_text(doc_dir=doc_dir).pages
    assert [page.text for page in pages] == [
        "testo riconosciuto dalla pagina 1",
        "testo riconosciuto dalla pagina 2",
    ]
    assert all(page.ocr for page in pages)
    document = read_document(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)
    assert document.status is DocumentStatus.READY
    run = load_ocr(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)
    assert run is not None
    assert (run.status, run.done, run.total) == (OcrStatus.DONE, 2, 2)


def test_run_ocr_records_the_current_ocr_prompt_on_read_pages(
    tmp_path: Path,
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=tmp_path)
    create_ocr(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)

    run_ocr(document_dir=doc_dir, read_page=lambda index: "testo letto")

    pages = read_text(doc_dir=doc_dir).pages
    assert {page.ocr_prompt for page in pages if page.ocr} == {"ocr-v2"}


def test_run_ocr_with_ollama_down_leaves_text_and_document_untouched(
    tmp_path: Path,
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=tmp_path)
    create_ocr(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)
    text_before = (doc_dir / "text.json").read_bytes()
    document_before = (doc_dir / "document.json").read_bytes()
    original_before = (doc_dir / "original.pdf").read_bytes()

    def down(index: int) -> str:
        raise CorrectorUnavailableError("ConnectionError: refused")

    with pytest.raises(CorrectorUnavailableError):
        run_ocr(document_dir=doc_dir, read_page=down)

    assert (doc_dir / "text.json").read_bytes() == text_before
    assert (doc_dir / "document.json").read_bytes() == document_before
    assert (doc_dir / "original.pdf").read_bytes() == original_before


def test_run_ocr_with_an_empty_transcript_keeps_the_document_without_text(
    tmp_path: Path,
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=tmp_path)
    create_ocr(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)

    run_ocr(document_dir=doc_dir, read_page=lambda index: "   ")

    assert all(page.no_text for page in read_text(doc_dir=doc_dir).pages)
    document = read_document(courses_dir=tmp_path, course_id=course_id, doc_id=DOC_ID)
    assert document.status is DocumentStatus.READY_NO_TEXT


def test_ocr_text_reaches_the_search_index(tmp_path: Path) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=tmp_path / "courses")
    create_ocr(courses_dir=tmp_path / "courses", course_id=course_id, doc_id=DOC_ID)
    store = JobStore(data_dir=tmp_path)
    index_path = tmp_path / "search.sqlite3"
    with search_session(store=store, path=index_path) as index:
        assert DOC_ID not in index.indexed_documents()

    run_ocr(document_dir=doc_dir, read_page=lambda index: "avviamento e azienda")

    with search_session(store=store, path=index_path) as index:
        assert DOC_ID in index.indexed_documents()


def test_run_ocr_stage_applies_the_memory_limit_before_reading_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, doc_dir = add_scanned_document(courses_dir=tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        ocr_runner, "_apply_memory_limit", lambda max_memory_mb: calls.append("limit")
    )
    original_read_document_in = ocr_runner.read_document_in

    def spy_read_document_in(doc_dir: Path) -> object:
        calls.append("read_document")
        return original_read_document_in(doc_dir=doc_dir)

    monkeypatch.setattr(ocr_runner, "read_document_in", spy_read_document_in)
    monkeypatch.setattr(
        ocr_runner,
        "_build_read_page",
        lambda document_dir, document: lambda index: "testo ocr",
    )

    ocr_runner.run_ocr_stage(document_dir=doc_dir)

    assert calls == ["limit", "read_document"]


def test_ocr_client_has_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hung (not down) Ollama would otherwise hold the single queue worker.
    _, doc_dir = add_scanned_document(courses_dir=tmp_path)
    created: list[dict[str, object]] = []

    class RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            created.append(kwargs)

    monkeypatch.setattr(ocr_runner, "Client", RecordingClient)
    monkeypatch.setattr(llm_corrector, "ensure_model", lambda **_: None)

    ocr_runner._build_read_page(
        document_dir=doc_dir, document=read_document_in(doc_dir=doc_dir)
    )

    assert created[0]["timeout"] == settings.ocr_timeout_s
