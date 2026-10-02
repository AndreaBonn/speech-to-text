"""Single boundary module for pypdfium2: PDF text extraction (D4, revised)."""

from pathlib import Path

import pypdfium2 as pdfium


def extract_pdf_pages(path: Path) -> tuple[str, ...]:
    """Return the text of each page, in page order."""
    pdf = pdfium.PdfDocument(path)
    try:
        return tuple(_page_text(pdf=pdf, index=index) for index in range(len(pdf)))
    finally:
        pdf.close()


def _page_text(pdf: pdfium.PdfDocument, index: int) -> str:
    page = pdf[index]
    try:
        textpage = page.get_textpage()
        try:
            return str(textpage.get_text_range())
        finally:
            textpage.close()
    finally:
        page.close()
