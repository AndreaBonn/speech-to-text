import json
from pathlib import Path

import pytest

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.web.document_store import read_text, write_text


def test_page_read_by_ocr_with_text_round_trips(tmp_path: Path) -> None:
    page = Page(text="Testo letto", no_text=False, ocr=True)

    write_text(
        doc_dir=tmp_path,
        extracted=ExtractedText(pages=(page,), status=DocumentStatus.READY),
    )
    loaded = read_text(doc_dir=tmp_path)

    assert loaded.pages == (page,)
    assert json.loads(s=(tmp_path / "text.json").read_text(encoding="utf-8"))[
        "pages"
    ] == [{"text": "Testo letto", "no_text": False, "ocr": True, "ocr_prompt": None}]


def test_page_below_threshold_round_trips_short_text(tmp_path: Path) -> None:
    # Extraction marks a page holding only a page number as no_text but keeps
    # the characters: this state is legitimate.
    page = Page(text="12", no_text=True)

    write_text(
        doc_dir=tmp_path,
        extracted=ExtractedText(pages=(page,), status=DocumentStatus.READY_NO_TEXT),
    )
    loaded = read_text(doc_dir=tmp_path)

    assert loaded.pages == (page,)
    assert json.loads(s=(tmp_path / "text.json").read_text(encoding="utf-8"))[
        "pages"
    ] == [{"text": "12", "no_text": True, "ocr": False, "ocr_prompt": None}]


def test_page_read_by_ocr_without_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR"):
        Page(text="  ", no_text=False, ocr=True)


def test_page_read_by_ocr_marked_no_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR"):
        Page(text="Testo letto", no_text=True, ocr=True)


def test_page_read_by_ocr_records_its_prompt_version() -> None:
    page = Page(text="Testo letto", no_text=False, ocr=True, ocr_prompt="ocr-v2")

    assert page.ocr_prompt == "ocr-v2"


def test_page_not_read_by_ocr_with_a_prompt_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR"):
        Page(text="Testo nativo", no_text=False, ocr_prompt="ocr-v2")
