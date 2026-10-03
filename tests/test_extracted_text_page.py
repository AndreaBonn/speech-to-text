import pytest

from sbobina.extracted_text import Page


def test_page_read_by_ocr_with_text_is_valid() -> None:
    page = Page(text="Testo letto", no_text=False, ocr=True)

    assert page.ocr is True


def test_page_below_threshold_keeps_its_short_text() -> None:
    # Extraction marks a page holding only a page number as no_text but keeps
    # the characters: this state is legitimate.
    page = Page(text="12", no_text=True)

    assert page.text == "12"


def test_page_read_by_ocr_without_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR"):
        Page(text="  ", no_text=False, ocr=True)


def test_page_read_by_ocr_marked_no_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR"):
        Page(text="Testo letto", no_text=True, ocr=True)
