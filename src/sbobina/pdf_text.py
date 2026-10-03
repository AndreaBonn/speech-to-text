"""Single boundary module for pypdfium2: PDF text extraction (D4, revised)."""

import io
from pathlib import Path

import pypdfium2 as pdfium


def render_pdf_page(path: Path, index: int, scale: float) -> bytes:
    """Render one page as a PNG image, for pages OCR must read (F5)."""
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[index]
        try:
            image = page.render(scale=scale).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        pdf.close()


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
