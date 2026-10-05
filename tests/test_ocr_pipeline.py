from collections.abc import Callable

import pytest

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.ocr_pipeline import ocr_missing_pages


def _extracted(pages: tuple[Page, ...]) -> ExtractedText:
    return ExtractedText(
        pages=pages, status=DocumentStatus.READY_NO_TEXT, encoding=None
    )


def test_native_text_pages_are_never_sent_to_read_page() -> None:
    extracted = _extracted((Page(text="Already here", no_text=False),))
    calls: list[int] = []

    def read_page(index: int) -> str:
        calls.append(index)
        return "should not be called"

    result = ocr_missing_pages(
        extracted=extracted,
        read_page=read_page,
        on_progress=lambda done, total: None,
        prompt_version="ocr-v2",
    )

    assert calls == []
    assert result.pages == extracted.pages
    assert result.status == DocumentStatus.READY


def test_ocr_page_with_text_is_marked_ready_and_flagged() -> None:
    extracted = _extracted((Page(text="", no_text=True),))

    result = ocr_missing_pages(
        extracted=extracted,
        read_page=lambda index: "Testo letto con OCR",
        on_progress=lambda done, total: None,
        prompt_version="ocr-v2",
    )

    assert result.status == DocumentStatus.READY
    assert result.pages[0].ocr is True
    assert result.pages[0].no_text is False
    assert result.pages[0].text == "Testo letto con OCR"


def test_ocr_page_with_empty_result_stays_no_text() -> None:
    extracted = _extracted((Page(text="", no_text=True),))

    result = ocr_missing_pages(
        extracted=extracted,
        read_page=lambda index: "   ",
        on_progress=lambda d, t: None,
        prompt_version="ocr-v2",
    )

    assert result.pages[0].no_text is True
    assert result.pages[0].ocr is False
    assert result.status == DocumentStatus.READY_NO_TEXT


def test_ocr_page_with_empty_result_logs_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    extracted = _extracted((Page(text="", no_text=True), Page(text="", no_text=True)))
    texts = {0: "Testo letto", 1: "   "}

    with caplog.at_level("WARNING", logger="sbobina.ocr_pipeline"):
        ocr_missing_pages(
            extracted=extracted,
            read_page=lambda index: texts[index],
            on_progress=lambda d, t: None,
            prompt_version="ocr-v2",
        )

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == ["OCR returned no text for page 2"]


def test_progress_reports_only_pages_actually_read() -> None:
    extracted = _extracted(
        (
            Page(text="Native", no_text=False),
            Page(text="", no_text=True),
            Page(text="", no_text=True),
        )
    )
    progress_calls: list[tuple[int, int]] = []

    ocr_missing_pages(
        extracted=extracted,
        read_page=lambda index: "Pagina letta",
        on_progress=lambda done, total: progress_calls.append((done, total)),
        prompt_version="ocr-v2",
    )

    assert progress_calls == [(1, 2), (2, 2)]


def test_read_page_exception_propagates_without_partial_result() -> None:
    extracted = _extracted((Page(text="", no_text=True), Page(text="", no_text=True)))

    def read_page(index: int) -> str:
        raise RuntimeError("Ollama down")

    with pytest.raises(RuntimeError):
        ocr_missing_pages(
            extracted=extracted,
            read_page=read_page,
            on_progress=lambda d, t: None,
            prompt_version="ocr-v2",
        )


def test_at_least_one_ocr_page_yields_ready_status() -> None:
    extracted = _extracted((Page(text="", no_text=True), Page(text="", no_text=True)))
    reads: Callable[[int], str] = lambda index: "x" if index == 0 else ""

    result = ocr_missing_pages(
        extracted=extracted,
        read_page=reads,
        on_progress=lambda d, t: None,
        prompt_version="ocr-v2",
    )

    assert result.status == DocumentStatus.READY
    assert result.pages[0].ocr is True
    assert result.pages[1].no_text is True


def test_ocr_pages_record_the_prompt_version_and_native_pages_do_not() -> None:
    extracted = _extracted(
        (Page(text="", no_text=True), Page(text="Already here", no_text=False))
    )

    result = ocr_missing_pages(
        extracted=extracted,
        read_page=lambda index: "letto",
        on_progress=lambda done, total: None,
        prompt_version="ocr-v2",
    )

    assert [page.ocr_prompt for page in result.pages] == ["ocr-v2", None]
