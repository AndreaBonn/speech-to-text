"""Pure orchestration for filling in no-text pages with OCR (F5)."""

import logging
from collections.abc import Callable
from dataclasses import replace

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page, normalize_pages

ReadPage = Callable[[int], str]
OcrProgress = Callable[[int, int], None]

logger = logging.getLogger(__name__)


def _ocr_page(
    page: Page, index: int, read_page: ReadPage, prompt_version: str | None
) -> Page:
    text = normalize_pages(texts=(read_page(index),))[0]
    if not text.strip():
        logger.warning("OCR returned no text for page %d", index + 1)
        return page
    return replace(page, text=text, no_text=False, ocr=True, ocr_prompt=prompt_version)


def ocr_missing_pages(
    extracted: ExtractedText,
    read_page: ReadPage,
    on_progress: OcrProgress,
    prompt_version: str,
) -> ExtractedText:
    """Replace every ``no_text`` page with the OCR transcript, if any text came back.

    Pages that already carry native text are never passed to ``read_page``.
    ``on_progress`` fires once per OCR attempt (not per page overall), after
    the result is known.
    """
    missing = [index for index, page in enumerate(extracted.pages) if page.no_text]
    pages = list(extracted.pages)
    for done, index in enumerate(missing, start=1):
        pages[index] = _ocr_page(
            page=pages[index],
            index=index,
            read_page=read_page,
            prompt_version=prompt_version,
        )
        on_progress(done, len(missing))
    status = (
        DocumentStatus.READY
        if any(not page.no_text for page in pages)
        else DocumentStatus.READY_NO_TEXT
    )
    return replace(extracted, pages=tuple(pages), status=status)
