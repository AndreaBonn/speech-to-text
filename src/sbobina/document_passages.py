"""Pure chunking of extracted document pages into indexed, citable passages.

One physical page is one passage; a page past LONG_PAGE_WORD_LIMIT splits into
overlapping word windows, never spanning two pages. See
specs/001-course-workspace/adr.md § D2 "Chunking".
"""

from collections.abc import Iterator
from dataclasses import dataclass

from sbobina.extracted_text import Page

LONG_PAGE_WORD_LIMIT = 400
WINDOW_WORD_COUNT = 300
WINDOW_OVERLAP_WORDS = 50
_WINDOW_STEP = WINDOW_WORD_COUNT - WINDOW_OVERLAP_WORDS


@dataclass(frozen=True)
class DocumentPassage:
    passage_id: str
    page: int
    chunk: int
    text: str


def chunk_document_pages(doc_id: str, pages: tuple[Page, ...]) -> list[DocumentPassage]:
    """Split each readable page into one or more ordered, citable passages."""
    passages = []
    for index, page in enumerate(pages):
        if page.no_text:
            continue
        passages.extend(
            _chunk_page(doc_id=doc_id, page_number=index + 1, text=page.text)
        )
    return passages


def _chunk_page(doc_id: str, page_number: int, text: str) -> list[DocumentPassage]:
    words = text.split()
    if not words:
        return []
    if len(words) <= LONG_PAGE_WORD_LIMIT:
        return [_passage(doc_id=doc_id, page_number=page_number, chunk=0, text=text)]
    return [
        _passage(
            doc_id=doc_id,
            page_number=page_number,
            chunk=chunk,
            text=" ".join(window),
        )
        for chunk, window in enumerate(_windows(words=words))
    ]


def _windows(words: list[str]) -> Iterator[list[str]]:
    total = len(words)
    start = 0
    while True:
        end = min(start + WINDOW_WORD_COUNT, total)
        yield words[start:end]
        if end == total:
            return
        start += _WINDOW_STEP


def _passage(doc_id: str, page_number: int, chunk: int, text: str) -> DocumentPassage:
    return DocumentPassage(
        passage_id=f"{doc_id}:p{page_number}:c{chunk}",
        page=page_number,
        chunk=chunk,
        text=text,
    )
