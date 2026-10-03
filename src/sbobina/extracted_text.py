"""Pure data model and normalization for text extracted from course documents."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from sbobina.document_models import DocumentStatus

# A hyphen at end-of-line splits a word across the line break; join it back
# rather than leave a dangling "-\n" that breaks search and citations.
_HYPHENATED_LINE_BREAK = r"(\w)-\n(\w)"
# More than half of a multi-page document sharing the same first/last line
# marks it a running header or footer (D4), not page content.
_REPEATED_EDGE_MAJORITY = 0.5


@dataclass(frozen=True)
class Page:
    text: str
    no_text: bool
    ocr: bool = False


@dataclass(frozen=True)
class ExtractedText:
    pages: tuple[Page, ...]
    status: DocumentStatus
    encoding: str | None = None


def _normalize_text(text: str) -> str:

    joined = re.sub(_HYPHENATED_LINE_BREAK, r"\1\2", text)
    return unicodedata.normalize("NFKC", joined)


def _majority_edge_line(lines_per_page: list[list[str]], pick_last: bool) -> str | None:
    total = len(lines_per_page)
    candidates = Counter(
        lines[-1] if pick_last else lines[0] for lines in lines_per_page if lines
    )
    if not candidates:
        return None
    line, count = candidates.most_common(1)[0]
    return line if count > total * _REPEATED_EDGE_MAJORITY else None


def _strip_repeated_edges(lines_per_page: list[list[str]]) -> list[list[str]]:
    header = _majority_edge_line(lines_per_page=lines_per_page, pick_last=False)
    footer = _majority_edge_line(lines_per_page=lines_per_page, pick_last=True)
    stripped = []
    for lines in lines_per_page:
        trimmed = list(lines)
        if len(trimmed) > 1 and header is not None and trimmed[0] == header:
            trimmed = trimmed[1:]
        if len(trimmed) > 1 and footer is not None and trimmed[-1] == footer:
            trimmed = trimmed[:-1]
        stripped.append(trimmed)
    return stripped


def normalize_pages(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Apply NFKC and dehyphenation per page, then drop a shared header/footer."""
    normalized = tuple(_normalize_text(text) for text in texts)
    if len(normalized) <= 1:
        return normalized
    lines_per_page = [page.split("\n") for page in normalized]
    stripped = _strip_repeated_edges(lines_per_page=lines_per_page)
    return tuple("\n".join(lines) for lines in stripped)
