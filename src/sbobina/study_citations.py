import re
import unicodedata
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from sbobina.models import Segment
from sbobina.study_models import (
    CitationMatch,
    ConceptItem,
    Rejection,
    RejectionReason,
    StudyItem,
    ValidatedItem,
    WordReference,
)

MIN_QUOTE_WORDS = 3
MAX_QUOTE_WORDS = 40
_APOSTROPHES = "'’‘ʼ"
_NONSPACE = re.compile(r"\S+")


@dataclass(frozen=True)
class _IndexedToken:
    text: str
    words: tuple[WordReference, ...]


def _without_punctuation(text: str) -> str:
    return "".join(
        " "
        if unicodedata.category(char).startswith("P") or char in _APOSTROPHES
        else char
        for char in text
    )


def _token_spans(text: str) -> tuple[tuple[str, int, int], ...]:
    spans = []
    # Keep raw offsets before NFKC can expand a ligature or compose an accent.
    for match in _NONSPACE.finditer(_without_punctuation(text=text)):
        normalized = unicodedata.normalize("NFKC", match.group()).casefold()
        for token in _without_punctuation(text=normalized).split():
            spans.append((token, match.start(), match.end()))
    return tuple(spans)


def normalize_tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token, _, _ in _token_spans(text=text))


def _indexed_tokens(segment: Segment, segment_index: int) -> list[_IndexedToken]:
    text = "".join(word.text for word in segment.words)
    owners = [
        WordReference(segment_index=segment_index, word_index=index)
        for index, word in enumerate(segment.words)
        for _ in word.text
    ]
    return [
        _IndexedToken(text=token, words=tuple(dict.fromkeys(owners[start:end])))
        for token, start, end in _token_spans(text=text)
    ]


def _window_tokens(
    segments: Sequence[Segment],
    segment_index: int,
    allowed: AbstractSet[int],
) -> list[_IndexedToken]:
    indices = [
        index
        for index in sorted(allowed)
        if segment_index <= index <= segment_index + 1 and index < len(segments)
    ]
    return [
        token
        for index in indices
        for token in _indexed_tokens(segment=segments[index], segment_index=index)
    ]


def _find_sequence(tokens: tuple[str, ...], quote: tuple[str, ...]) -> int | None:
    if not quote:
        return None
    return next(
        (
            index
            for index in range(len(tokens) - len(quote) + 1)
            if tokens[index : index + len(quote)] == quote
        ),
        None,
    )


def _resolve_match(
    segments: Sequence[Segment],
    tokens: list[_IndexedToken],
) -> CitationMatch:
    references = tuple(dict.fromkeys(ref for token in tokens for ref in token.words))
    first = references[0]
    return CitationMatch(
        segment_index=first.segment_index,
        word_indices=references,
        timestamp=segments[first.segment_index].words[first.word_index].start,
    )


def locate_quote(
    segments: Sequence[Segment],
    segment_index: int,
    quote: str,
    allowed: AbstractSet[int],
) -> CitationMatch | Rejection:
    """Resolve 3-40 tokens within the cited passage and its allowed successor."""
    if segment_index not in allowed or not 0 <= segment_index < len(segments):
        return Rejection(reason=RejectionReason.PASSAGE_NOT_IN_BLOCK)
    quote_tokens = normalize_tokens(text=quote)
    if len(quote_tokens) < MIN_QUOTE_WORDS:
        return Rejection(reason=RejectionReason.QUOTE_TOO_SHORT)
    if len(quote_tokens) > MAX_QUOTE_WORDS:
        return Rejection(reason=RejectionReason.QUOTE_TOO_LONG)
    tokens = _window_tokens(
        segments=segments, segment_index=segment_index, allowed=allowed
    )
    index = _find_sequence(
        tokens=tuple(token.text for token in tokens), quote=quote_tokens
    )
    if index is None:
        return Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)
    return _resolve_match(
        segments=segments, tokens=tokens[index : index + len(quote_tokens)]
    )


def validate_item(
    segments: Sequence[Segment],
    item: StudyItem,
    allowed: AbstractSet[int],
) -> ValidatedItem | Rejection:
    """Reject the whole item if any citation fails, including uncited concepts."""
    if not item.citations:
        return Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)
    matches = []
    for citation in item.citations:
        match = locate_quote(
            segments=segments,
            segment_index=citation.segment_index,
            quote=citation.quote,
            allowed=allowed,
        )
        if isinstance(match, Rejection):
            return match
        matches.append(match)
    if isinstance(item, ConceptItem) and not _has_cited_term(item=item):
        return Rejection(reason=RejectionReason.TERM_NOT_IN_QUOTE)
    return ValidatedItem(item=item, citations=tuple(matches))


def _has_cited_term(item: ConceptItem) -> bool:
    return any(
        _find_sequence(
            tokens=normalize_tokens(text=citation.quote),
            quote=normalize_tokens(text=item.term),
        )
        is not None
        for citation in item.citations
    )
