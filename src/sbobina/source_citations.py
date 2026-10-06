"""Resolve a proposed citation against the passages given to the model.

Extends study_citations.py's quote validation (reused, not copied) from one
lecture's own segments to the cross-source passages retrieval.py hands to a
prompt: documents resolve to (doc_id, page); lectures resolve to (job_id,
timestamp). The timestamp is the anchor segment retrieval matched, kept fixed
by lecture_windows.py regardless of how wide the window grew around it, so no
further word-level resolution is needed here. Pure, no I/O.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sbobina.retrieval import DocumentSource, RetrievalSource, RetrievedPassage
from sbobina.study_citations import MAX_QUOTE_WORDS, MIN_QUOTE_WORDS, normalize_tokens

_LABEL_RE = re.compile(r"^P([0-9]+)$")


class SourceRejectionReason(StrEnum):
    PASSAGE_NOT_GIVEN = "PASSAGE_NOT_GIVEN"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    QUOTE_LENGTH = "QUOTE_LENGTH"


@dataclass(frozen=True)
class SourceRejection:
    reason: SourceRejectionReason


@dataclass(frozen=True)
class ProposedSourceCitation:
    label: str
    quote: str


@dataclass(frozen=True)
class DocumentCitation:
    doc_id: str
    page: int


@dataclass(frozen=True)
class LectureCitation:
    job_id: str
    timestamp: float


@dataclass(frozen=True)
class SourceCitation:
    passage_id: str
    quote: str
    location: DocumentCitation | LectureCitation


def _passage_at(
    passages: Sequence[RetrievedPassage], label: str
) -> RetrievedPassage | None:
    match = _LABEL_RE.fullmatch(label)
    if match is None:
        return None
    index = int(match.group(1)) - 1
    if not 0 <= index < len(passages):
        return None
    return passages[index]


def _contains_sequence(tokens: tuple[str, ...], quote: tuple[str, ...]) -> bool:
    span = len(quote)
    return any(tokens[i : i + span] == quote for i in range(len(tokens) - span + 1))


def _location(source: RetrievalSource) -> DocumentCitation | LectureCitation:
    if isinstance(source, DocumentSource):
        return DocumentCitation(doc_id=source.doc_id, page=source.page)
    return LectureCitation(job_id=source.job_id, timestamp=source.start)


def _bounded_quote(quote: str) -> str:
    """The quote cut to its first MAX_QUOTE_WORDS tokens, at a word boundary.

    Measured (F81): on lecture material qwen copies 50-70 word stretches and
    every such question was dropped. A prefix of a contiguous exact match is
    still one, so the 3-40 word rule holds on what is stored.
    """
    words = quote.split()
    if len(normalize_tokens(text=quote)) <= MAX_QUOTE_WORDS:
        return quote
    while len(normalize_tokens(text=" ".join(words))) > MAX_QUOTE_WORDS:
        words = words[:-1]
    return " ".join(words)


def _passage_with_quote(
    labelled: RetrievedPassage,
    passages: Sequence[RetrievedPassage],
    quote_tokens: tuple[str, ...],
) -> RetrievedPassage | None:
    # The labelled passage first; then any other passage the model was given,
    # since a 9B model copies the right words under the wrong label (T046).
    return next(
        (
            candidate
            for candidate in (labelled, *passages)
            if _contains_sequence(
                tokens=normalize_tokens(text=candidate.text), quote=quote_tokens
            )
        ),
        None,
    )


def resolve_citation(
    passages: Sequence[RetrievedPassage],
    citation: ProposedSourceCitation,
) -> SourceCitation | SourceRejection:
    """Resolve citation against the passages numbered P1..Pn given to the model."""
    passage = _passage_at(passages=passages, label=citation.label)
    if passage is None:
        return SourceRejection(reason=SourceRejectionReason.PASSAGE_NOT_GIVEN)
    quote = _bounded_quote(quote=citation.quote)
    quote_tokens = normalize_tokens(text=quote)
    # _bounded_quote already caps the length at MAX_QUOTE_WORDS.
    if len(quote_tokens) < MIN_QUOTE_WORDS:
        return SourceRejection(reason=SourceRejectionReason.QUOTE_LENGTH)
    found = _passage_with_quote(
        labelled=passage, passages=passages, quote_tokens=quote_tokens
    )
    if found is None:
        return SourceRejection(reason=SourceRejectionReason.QUOTE_NOT_FOUND)
    passage = found
    return SourceCitation(
        passage_id=passage.passage_id,
        quote=quote,
        location=_location(source=passage.source),
    )
