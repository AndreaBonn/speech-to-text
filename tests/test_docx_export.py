from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from sbobina.docx_export import render_book_docx

A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7


def _open(data: bytes) -> DocxDocument:
    return Document(BytesIO(data))


def test_render_book_docx_title_then_one_paragraph_per_block() -> None:
    document = _open(
        render_book_docx(title="Diritto privato", paragraphs=["Primo.", "Secondo."])
    )

    texts = [p.text for p in document.paragraphs]
    assert texts == ["Diritto privato", "Primo.", "Secondo."]
    title_style = document.paragraphs[0].style
    assert title_style is not None
    assert title_style.name == "Title"
    assert document.core_properties.title == "Diritto privato"


def test_render_book_docx_body_is_justified_with_first_line_indent() -> None:
    document = _open(render_book_docx(title="T", paragraphs=["Uno.", "Due."]))

    body = document.styles["Normal"]
    assert body.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert body.paragraph_format.first_line_indent is not None
    assert body.paragraph_format.first_line_indent > 0


def test_render_book_docx_page_is_a4() -> None:
    section = _open(render_book_docx(title="T", paragraphs=["x"])).sections[0]

    assert section.page_width is not None
    assert section.page_height is not None
    assert round(section.page_width.cm, 1) == round(Cm(A4_WIDTH_CM).cm, 1)
    assert round(section.page_height.cm, 1) == round(Cm(A4_HEIGHT_CM).cm, 1)


def test_render_book_docx_footer_has_page_number_field() -> None:
    section = _open(render_book_docx(title="T", paragraphs=["x"])).sections[0]

    footer_xml = section.footer.paragraphs[0]._p.xml
    assert "PAGE" in footer_xml


def test_render_book_docx_text_is_marked_italian() -> None:
    document = _open(render_book_docx(title="T", paragraphs=["x"]))

    normal_xml = document.styles["Normal"].element.xml
    assert 'w:val="it-IT"' in normal_xml


def test_render_book_docx_title_uses_body_serif_not_word_default() -> None:
    document = _open(render_book_docx(title="T", paragraphs=["x"]))

    assert document.styles["Title"].font.name == document.styles["Normal"].font.name
