import io
from pathlib import Path

import pytest
from document_fixtures import write_pdf, write_pdf_with_mediabox
from PIL import Image
from pypdfium2 import PdfiumError

from sbobina.pdf_text import MAX_RENDER_SIDE_PX, render_pdf_page


def test_render_pdf_page_unit_scale_matches_mediabox_pixels(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    write_pdf(path=pdf_path, texts=("First page", "Second page"))

    png = render_pdf_page(path=pdf_path, index=0, scale=1.0)

    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    assert image.size == (612, 792)


def test_render_pdf_page_scale_doubles_pixel_dimensions(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    write_pdf(path=pdf_path, texts=("Only page",))

    small = Image.open(io.BytesIO(render_pdf_page(path=pdf_path, index=0, scale=1.0)))
    large = Image.open(io.BytesIO(render_pdf_page(path=pdf_path, index=0, scale=2.0)))

    assert large.size[0] == small.size[0] * 2
    assert large.size[1] == small.size[1] * 2


def test_render_pdf_page_caps_the_long_side_of_a_huge_mediabox(tmp_path: Path) -> None:
    pdf_path = tmp_path / "huge.pdf"
    write_pdf_with_mediabox(path=pdf_path, width_pt=20000, height_pt=10000)

    png = render_pdf_page(path=pdf_path, index=0, scale=10.0)

    image = Image.open(io.BytesIO(png))
    assert max(image.size) == MAX_RENDER_SIDE_PX


def test_render_pdf_page_out_of_range_index_raises(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    write_pdf(path=pdf_path, texts=("Only page",))

    with pytest.raises(PdfiumError):
        render_pdf_page(path=pdf_path, index=5, scale=1.0)
