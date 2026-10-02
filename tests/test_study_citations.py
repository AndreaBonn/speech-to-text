import pytest

from sbobina.models import Segment, Word
from sbobina.study_citations import locate_quote, normalize_tokens, validate_item
from sbobina.study_models import (
    Citation,
    CitationMatch,
    ConceptItem,
    QuestionItem,
    Rejection,
    RejectionReason,
    SummaryItem,
    ValidatedItem,
    WordReference,
)

QUOTE = "causa del contratto è illecita"
TEXT = "la causa del contratto è illecita quando contrasta con norme imperative"
ALLOWED = frozenset({12, 13, 14})


def segment(text: str, start: float = 100.0) -> Segment:
    words = tuple(
        Word(start=start + i, end=start + i + 0.5, text=" " + token, probability=1.0)
        for i, token in enumerate(text.split())
    )
    return Segment(start=start, end=start + len(words), words=words)


def passages(*texts: str) -> tuple[Segment, ...]:
    empty = Segment(start=0.0, end=0.0, words=())
    return (empty,) * 12 + tuple(
        segment(text=text, start=100.0 + i * 20) for i, text in enumerate(texts)
    )


def test_locate_quote_d5_resolves_cause_timestamp_and_word_indices() -> None:
    result = locate_quote(
        segments=passages(TEXT), segment_index=12, quote=QUOTE, allowed=ALLOWED
    )
    assert result == CitationMatch(
        segment_index=12,
        timestamp=101.0,
        word_indices=tuple(
            WordReference(segment_index=12, word_index=i) for i in range(1, 6)
        ),
    )


@pytest.mark.parametrize(
    ("index", "quote", "reason"),
    [
        (12, "il contratto è nullo", RejectionReason.QUOTE_NOT_FOUND),
        (99, QUOTE, RejectionReason.PASSAGE_NOT_IN_BLOCK),
        (-1, QUOTE, RejectionReason.PASSAGE_NOT_IN_BLOCK),
        (12, "causa del", RejectionReason.QUOTE_TOO_SHORT),
        (12, "", RejectionReason.QUOTE_TOO_SHORT),
        (12, "causa " * 41, RejectionReason.QUOTE_TOO_LONG),
    ],
)
def test_locate_quote_rejects_invalid_citations(
    index: int,
    quote: str,
    reason: RejectionReason,
) -> None:
    assert locate_quote(
        segments=passages(TEXT), segment_index=index, quote=quote, allowed=ALLOWED
    ) == Rejection(reason=reason)


@pytest.mark.parametrize(
    "text", [" L’ATTO,  è: ILLECITO! ", "l'atto è illecito", "ｌ’ａｔｔｏ è illecito"]
)
def test_normalize_tokens_unifies_nfkc_case_apostrophes_and_punctuation(
    text: str,
) -> None:
    assert normalize_tokens(text=text) == ("l", "atto", "è", "illecito")
    result = locate_quote(
        segments=passages("l'atto è illecito"),
        segment_index=12,
        quote=text,
        allowed=ALLOWED,
    )
    assert isinstance(result, CitationMatch)
    assert result.timestamp == 100.0


def test_normalize_tokens_keeps_accents_and_rejects_punctuation_only() -> None:
    assert normalize_tokens(text="... ; !") == ()
    assert normalize_tokens(text="È perché") == ("è", "perché")


@pytest.mark.parametrize("count", [3, 40])
def test_locate_quote_accepts_inclusive_length_boundaries(count: int) -> None:
    quote = " ".join(f"parola{i}" for i in range(count))
    result = locate_quote(
        segments=passages(quote), segment_index=12, quote=quote, allowed=ALLOWED
    )
    assert isinstance(result, CitationMatch)
    assert len(result.word_indices) == count


def test_locate_quote_accepts_adjacent_passages_but_rejects_a_gap() -> None:
    adjacent = locate_quote(
        segments=passages("la causa", "del contratto è illecita"),
        segment_index=12,
        quote=QUOTE,
        allowed=ALLOWED,
    )
    assert isinstance(adjacent, CitationMatch)
    assert adjacent.timestamp == 101.0
    assert adjacent.word_indices == (
        WordReference(segment_index=12, word_index=1),
        *(WordReference(segment_index=13, word_index=i) for i in range(4)),
    )
    assert locate_quote(
        segments=passages("la causa", "altre parole", "del contratto è illecita"),
        segment_index=12,
        quote=QUOTE,
        allowed=frozenset({12, 14}),
    ) == Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)


def test_locate_quote_does_not_cross_into_a_segment_outside_the_block() -> None:
    segments = passages("la causa", "del contratto è illecita")
    assert isinstance(
        locate_quote(segments=segments, segment_index=12, quote=QUOTE, allowed=ALLOWED),
        CitationMatch,
    )
    assert locate_quote(
        segments=segments, segment_index=12, quote=QUOTE, allowed={12}
    ) == Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)


def test_locate_quote_rejects_real_quote_outside_block() -> None:
    segments = passages(TEXT)
    assert isinstance(
        locate_quote(segments=segments, segment_index=12, quote=QUOTE, allowed={12}),
        CitationMatch,
    )
    assert locate_quote(
        segments=segments, segment_index=12, quote=QUOTE, allowed={13}
    ) == Rejection(reason=RejectionReason.PASSAGE_NOT_IN_BLOCK)


def test_locate_quote_uses_first_occurrence_and_can_resolve_next_passage() -> None:
    segments = passages("inizio", f"{QUOTE} e {QUOTE}")
    result = locate_quote(
        segments=segments, segment_index=12, quote=QUOTE, allowed=ALLOWED
    )
    assert isinstance(result, CitationMatch)
    assert result.segment_index == 13
    assert result.timestamp == 120.0
    assert result.word_indices[0] == WordReference(segment_index=13, word_index=0)


def test_locate_quote_handles_split_words_and_multiple_tokens_per_word() -> None:
    words = tuple(
        Word(start=float(i), end=i + 0.5, text=text, probability=1.0)
        for i, text in enumerate((" l’", "at", "to", " è illecito"))
    )
    segments = (Segment(start=0.0, end=4.0, words=words),)
    result = locate_quote(
        segments=segments, segment_index=0, quote="l'atto è illecito", allowed={0}
    )
    assert result == CitationMatch(
        segment_index=0,
        timestamp=0.0,
        word_indices=tuple(
            WordReference(segment_index=0, word_index=i) for i in range(4)
        ),
    )


@pytest.mark.parametrize("item_type", [SummaryItem, QuestionItem])
def test_validate_item_keeps_supported_items_and_rejects_one_bad_citation(
    item_type: type[SummaryItem] | type[QuestionItem],
) -> None:
    good = Citation(segment_index=12, quote=QUOTE)
    bad = Citation(segment_index=12, quote="il contratto è nullo")
    item = item_type("testo", citations=(good,))
    result = validate_item(segments=passages(TEXT), item=item, allowed=ALLOWED)
    assert isinstance(result, ValidatedItem)
    assert result.item == item
    assert result.citations[0].timestamp == 101.0
    assert validate_item(
        segments=passages(TEXT),
        item=item_type("testo", citations=(good, bad)),
        allowed=ALLOWED,
    ) == Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)


def test_validate_item_rejects_items_without_citations() -> None:
    assert validate_item(
        segments=passages(TEXT),
        item=SummaryItem(text="testo", citations=()),
        allowed=ALLOWED,
    ) == Rejection(reason=RejectionReason.QUOTE_NOT_FOUND)


@pytest.mark.parametrize("term", ["contratto", "CAUSA del contratto"])
def test_validate_item_requires_term_in_at_least_one_quote(term: str) -> None:
    citations = (
        Citation(segment_index=12, quote="contrasta con norme imperative"),
        Citation(segment_index=12, quote=QUOTE),
    )
    item = ConceptItem(term=term, explanation="spiegazione", citations=citations)
    result = validate_item(segments=passages(TEXT), item=item, allowed=ALLOWED)
    assert isinstance(result, ValidatedItem)
    assert result.item == item
    assert len(result.citations) == 2


@pytest.mark.parametrize("term", ["contratti", "causa illecita", "norme", ""])
def test_validate_item_rejects_term_absent_from_quote_even_if_present_elsewhere(
    term: str,
) -> None:
    item = ConceptItem(
        term=term,
        explanation=f"Spiegazione: {term}",
        citations=(Citation(segment_index=12, quote=QUOTE),),
    )
    assert validate_item(
        segments=passages(TEXT), item=item, allowed=ALLOWED
    ) == Rejection(
        reason=RejectionReason.TERM_NOT_IN_QUOTE,
    )
