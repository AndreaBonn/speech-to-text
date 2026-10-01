from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.styles import CT_Style
from docx.section import Section
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph

PAGE_WIDTH = Cm(21.0)
PAGE_HEIGHT = Cm(29.7)
PAGE_MARGIN = Cm(2.5)
# Cambria is metric-compatible with LibreOffice's Caladea, so the layout
# holds when the file is opened outside Word.
BODY_FONT = "Cambria"
BODY_SIZE = Pt(12)
LINE_SPACING = 1.15
FIRST_LINE_INDENT = Cm(0.6)
LANGUAGE = "it-IT"
TITLE_SIZE = Pt(24)
# Word's default Title is blue Calibri Light, foreign to a serif book page.
TITLE_COLOR = RGBColor(0x22, 0x22, 0x22)


def _set_language(style_element: CT_Style) -> None:
    run_properties = style_element.get_or_add_rPr()
    language = OxmlElement("w:lang")
    language.set(qn("w:val"), LANGUAGE)
    run_properties.append(language)


def _add_page_number(paragraph: Paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    paragraph._p.append(field)


def _set_up_page(section: Section) -> None:
    section.page_width, section.page_height = PAGE_WIDTH, PAGE_HEIGHT
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, PAGE_MARGIN)


def _set_up_styles(document: DocxDocument) -> None:
    body = document.styles["Normal"]
    body.font.name = BODY_FONT
    body.font.size = BODY_SIZE
    body.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    body.paragraph_format.first_line_indent = FIRST_LINE_INDENT
    body.paragraph_format.line_spacing = LINE_SPACING
    body.paragraph_format.space_after = Pt(0)
    _set_language(style_element=body.element)
    # Justified Italian text without hyphenation leaves wide word gaps.
    document.settings.element.append(OxmlElement("w:autoHyphenation"))

    title_style = document.styles["Title"]
    title_style.font.name = BODY_FONT
    title_style.font.size = TITLE_SIZE
    title_style.font.color.rgb = TITLE_COLOR


def render_book_docx(title: str, paragraphs: list[str]) -> bytes:
    """Lay out the transcript as a printable A4 book-style document.

    Parameters
    ----------
    title : str
        Document title, shown as the first heading and in the file metadata.
    paragraphs : list[str]
        Body paragraphs, already free of timestamps and review marks.

    Returns
    -------
    bytes
        The ``.docx`` file content.
    """
    document = Document()
    section = document.sections[0]
    _set_up_page(section=section)
    _set_up_styles(document=document)
    document.core_properties.title = title
    heading = document.add_paragraph(title, style="Title")
    heading.paragraph_format.first_line_indent = Cm(0)
    for text in paragraphs:
        document.add_paragraph(text)
    _add_page_number(paragraph=section.footer.paragraphs[0])

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
