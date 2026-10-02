import pytest
from conftest import make_word

from sbobina.edits import MAX_ANCHOR_TOKENS, Edit, apply_edits, find_spans
from sbobina.models import Word


def _words(text: str) -> tuple[Word, ...]:
    return tuple(make_word(f" {w}", i * 0.5, 0.6) for i, w in enumerate(text.split()))


def _numbered_sentence(length: int) -> str:
    return " ".join(f"parola{i}" for i in range(length))


def test_apply_edits_anchor_at_token_limit_is_applied() -> None:
    sentence = _numbered_sentence(MAX_ANCHOR_TOKENS)
    words = _words(f"{sentence} legione")
    anchor = " ".join([*sentence.split()[1:], "legione"])

    result = apply_edits(
        words, [Edit(original=anchor, corrected=anchor.replace("legione", "lesione"))]
    )

    assert result.words[-1].text == " lesione"


def test_apply_edits_anchor_over_token_limit_is_rejected_as_too_long() -> None:
    sentence = _numbered_sentence(MAX_ANCHOR_TOKENS)
    words = _words(f"{sentence} legione")
    anchor = f"{sentence} legione"

    result = apply_edits(
        words, [Edit(original=anchor, corrected=anchor.replace("legione", "lesione"))]
    )

    assert [r.reason for r in result.rejected] == ["modifica troppo lunga"]
    assert result.words == words


def test_find_spans_never_starts_a_span_on_a_punctuation_only_word() -> None:
    words = _words("la – legione")

    assert find_spans(words, ["legione"]) == [(2, 3)]


def test_apply_edits_after_punctuation_only_word_is_not_ambiguous() -> None:
    words = _words("la – legione degli interessi")

    result = apply_edits(words, [Edit(original="legione", corrected="lesione")])

    assert result.rejected == []
    assert result.words[2].text == " lesione"


def test_apply_edits_on_empty_chunk_rejects_with_zero_start() -> None:
    result = apply_edits((), [Edit(original="legione", corrected="lesione")])

    assert [(r.start, r.reason) for r in result.rejected] == [
        (0.0, "testo originale non trovato")
    ]


def test_apply_edits_exactly_three_changed_words_are_applied() -> None:
    words = _words("il gatto nero salta sul tetto")

    result = apply_edits(
        words,
        [
            Edit(
                original="il gatto nero salta sul tetto",
                corrected="il matto vero salda sul tetto",
            )
        ],
    )

    assert result.rejected == []
    assert " ".join(w.text.strip() for w in result.words) == (
        "il matto vero salda sul tetto"
    )


def test_apply_edits_similarity_threshold_keeps_sound_alike_rejects_meaning_flip() -> (
    None
):
    words = _words("il fatto comunicato non era ammesso")

    result = apply_edits(
        words,
        [
            Edit(original="fatto comunicato", corrected="fatto giudicato"),
            Edit(original="era ammesso", corrected="era escluso"),
        ],
    )

    assert [(c.original, c.corrected) for c in result.applied] == [
        ("comunicato", "giudicato")
    ]
    assert [r.reason for r in result.rejected] == ["troppo diverso dal suono originale"]


@pytest.mark.parametrize("text", ["legione", "la legione"])
def test_apply_edits_empty_original_never_changes_the_words(text: str) -> None:
    words = _words(text)

    result = apply_edits(words, [Edit(original="", corrected="lesione")])

    assert result.words == words
    assert result.applied == []
    assert len(result.rejected) == 1


def test_apply_edits_original_not_found_is_dated_at_the_chunk_start() -> None:
    words = tuple(
        make_word(f" {w}", 12.0 + i * 0.5) for i, w in enumerate(["la", "legione"])
    )

    result = apply_edits(words, [Edit(original="Sennberg", corrected="Heisenberg")])

    assert [(r.start, r.reason) for r in result.rejected] == [
        (12.0, "testo originale non trovato")
    ]
