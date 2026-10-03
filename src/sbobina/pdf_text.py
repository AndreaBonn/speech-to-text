"""Single boundary module for pypdfium2: PDF text extraction (D4, revised)."""

import io
from pathlib import Path

import pypdfium2 as pdfium

# A4 (security): an oversized MediaBox rendered at face value can allocate
# gigabytes. Cap the long side of the rendered image regardless of scale.
MAX_RENDER_SIDE_PX = 2500


def render_pdf_page(path: Path, index: int, scale: float) -> bytes:
    """Render one page as a PNG image, for pages OCR must read (F5)."""
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[index]
        try:
            capped_scale = _capped_scale(page=page, scale=scale)
            image = page.render(scale=capped_scale).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        pdf.close()


def _capped_scale(page: pdfium.PdfPage, scale: float) -> float:
    width_pt, height_pt = page.get_size()
    long_side_pt = max(float(width_pt), float(height_pt))
    return float(min(scale, MAX_RENDER_SIDE_PX / long_side_pt))


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
