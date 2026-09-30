import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.correction import (
    CorrectorUnavailableError,
    Edit,
    InvalidResponseError,
    apply_edits,
    chunk_segments,
    correct_transcript,
)
from sbobina.models import Word


def _words(text: str) -> tuple[Word, ...]:
    return tuple(make_word(f" {w}", i * 0.5, 0.6) for i, w in enumerate(text.split()))


def test_apply_edits_replaces_single_misheard_word_and_keeps_punctuation() -> None:
    words = _words("per quanto riguarda la legione, degli interessi")

    result = apply_edits(words, [Edit(original="legione", corrected="lesione")])

    assert (
        "".join(w.text for w in result.words)
        == " per quanto riguarda la lesione, degli interessi"
    )
    assert [(c.original, c.corrected, c.start) for c in result.applied] == [
        ("legione,", "lesione,", 2.0)
    ]
    assert result.rejected == []


def test_apply_edits_corrected_word_is_no_longer_flagged_uncertain() -> None:
    words = _words("ha esinto il credito")

    result = apply_edits(words, [Edit(original="esinto", corrected="estinto")])

    assert result.words[1].probability == 1.0


def test_apply_edits_two_misheard_words_collapse_into_one() -> None:
    words = _words("il teorema di Noether con leghe simmetrie")

    result = apply_edits(words, [Edit(original="con leghe", corrected="collega")])

    assert (
        "".join(w.text for w in result.words)
        == " il teorema di Noether collega simmetrie"
    )
    assert len(result.words) == len(words) - 1


def test_apply_edits_long_quoted_sentence_changes_only_the_misheard_word() -> None:
    words = _words("quando sentite la sentenza è passata in comunicato oggi")

    result = apply_edits(
        words,
        [
            Edit(
                original="quando sentite la sentenza è passata in comunicato",
                corrected="quando sentite la sentenza è passata in giudicato",
            )
        ],
    )

    assert [(c.original, c.corrected) for c in result.applied] == [
        ("comunicato", "giudicato")
    ]
    assert result.words[7].text == " giudicato"
    assert result.words[0].probability == 0.6


def test_apply_edits_rejects_added_words() -> None:
    words = _words("a pagarmi la stessa e poi")

    result = apply_edits(
        words, [Edit(original="pagarmi la stessa", corrected="pagarmi la stessa somma")]
    )

    assert result.words == words
    assert result.rejected[0].reason == "aggiunge o toglie parole"


def test_apply_edits_rejects_removed_words() -> None:
    words = _words("prende il nome di di attore")

    result = apply_edits(
        words, [Edit(original="nome di di attore", corrected="nome di attore")]
    )

    assert result.words == words
    assert result.rejected[0].reason == "aggiunge o toglie parole"


def test_apply_edits_rejects_original_not_found() -> None:
    words = _words("il teorema di Noether")

    result = apply_edits(words, [Edit(original="Sennberg", corrected="Heisenberg")])

    assert result.words == words
    assert result.rejected[0].reason == "testo originale non trovato"


def test_apply_edits_rejects_ambiguous_original() -> None:
    words = _words("la casa e la casa")

    result = apply_edits(words, [Edit(original="casa", corrected="cassa")])

    assert result.words == words
    assert result.rejected[0].reason == "testo originale ambiguo"


def test_apply_edits_rejects_rewrite_that_does_not_sound_alike() -> None:
    words = _words("diciamo di mangiare un copione di vita")

    result = apply_edits(
        words,
        [Edit(original="mangiare un copione", corrected="considerare il debitore")],
    )

    assert result.words == words
    assert result.rejected[0].reason == "troppo diverso dal suono originale"


def test_apply_edits_rejects_more_than_three_changed_words() -> None:
    words = _words("il gatto nero salta sul tetto rosso")

    result = apply_edits(
        words,
        [
            Edit(
                original="il gatto nero salta sul tetto rosso",
                corrected="il matto vero salda sul letto grosso",
            )
        ],
    )

    assert result.words == words
    assert result.rejected[0].reason == "modifica troppo lunga"


def test_apply_edits_ignores_no_op_edit() -> None:
    words = _words("tutto giusto")

    result = apply_edits(words, [Edit(original="giusto", corrected="giusto")])

    assert result.words == words
    assert result.applied == []
    assert result.rejected == []


def test_chunk_segments_respects_word_budget_at_segment_boundaries() -> None:
    segments = [make_segment(list(_words("a b c"))) for _ in range(5)]

    chunks = chunk_segments(tuple(segments), max_words=7)

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]


def test_correct_transcript_passes_previous_chunk_as_context_and_applies_edits() -> (
    None
):
    transcript = make_transcript(
        [
            make_segment(list(_words("la legione degli interessi"))),
            make_segment(list(_words("ha esinto il credito"))),
        ]
    )
    calls: list[tuple[str, str]] = []

    def fake_corrector(text: str, context: str) -> list[Edit]:
        calls.append((text, context))
        return [
            Edit(original="legione", corrected="lesione"),
            Edit(original="esinto", corrected="estinto"),
        ]

    result = correct_transcript(transcript, corrector=fake_corrector, max_words=4)

    assert calls[0] == ("la legione degli interessi", "")
    assert calls[1] == ("ha esinto il credito", "la lesione degli interessi")
    assert result.transcript.text == "la lesione degli interessi ha estinto il credito"
    assert len(result.applied) == 2
    assert len(result.rejected) == 2


def test_apply_edits_rejects_replacement_that_grows_word_count() -> None:
    words = _words("la sentenza comunicato oggi")

    result = apply_edits(
        words,
        [
            Edit(
                original="la sentenza comunicato", corrected="la sentenza con giudicato"
            )
        ],
    )

    assert result.words == words
    assert result.rejected[0].reason == "aggiunge o toglie parole"


def test_correct_transcript_merge_across_segments_extends_segment_end() -> None:
    first = make_segment(
        [make_word(" il", 0.0), make_word(" teorema", 0.5), make_word(" con", 1.0)]
    )
    second = make_segment([make_word(" leghe", 1.5)])
    third = make_segment([make_word(" simmetrie", 2.0)])
    transcript = make_transcript([first, second, third])

    result = correct_transcript(
        transcript,
        corrector=lambda text, context: [
            Edit(original="con leghe", corrected="collega")
        ],
        max_words=10,
    )

    segments = result.transcript.segments
    assert result.transcript.text == "il teorema collega simmetrie"
    assert segments[0].end == second.end
    assert [s.text for s in segments] == ["il teorema collega", "simmetrie"]


def test_apply_edits_elision_split_by_whisper_is_not_a_correction() -> None:
    words = (
        make_word(" davanti", 0.0, 0.6),
        make_word(" all", 0.5, 0.6),
        make_word("'ambito", 0.7, 0.5),
        make_word(" del", 1.0, 0.6),
        make_word(" progetto", 1.5, 0.6),
    )

    result = apply_edits(
        words,
        [Edit(original="all'ambito del progetto", corrected="all'ambito del processo")],
    )

    assert [(c.original, c.corrected) for c in result.applied] == [
        ("progetto", "processo")
    ]
    assert result.words[2].probability == 0.5


def test_apply_edits_corrected_word_remembers_what_whisper_heard() -> None:
    words = _words("per la legione, degli interessi")

    result = apply_edits(words, [Edit(original="legione", corrected="lesione")])

    assert result.words[2].corrected_from == "legione"


def test_apply_edits_rejection_carries_similarity_and_sentence_start() -> None:
    words = _words("la tutela giustiziaria dei diritti")

    result = apply_edits(
        words,
        [Edit(original="tutela giustiziaria", corrected="tutela giurisdizionale")],
    )

    rejected = result.rejected[0]
    assert rejected.reason == "troppo diverso dal suono originale"
    assert rejected.similarity == pytest.approx(0.59, abs=0.01)
    assert rejected.start == words[1].start


def test_correct_transcript_skips_chunk_with_invalid_response_and_records_it() -> None:
    transcript = make_transcript(
        [
            make_segment(list(_words("ha esinto il credito"))),
            make_segment([make_word(f" p{i}", 10.0 + i) for i in range(4)]),
        ]
    )

    def corrector(text: str, context: str) -> list[Edit]:
        if text.startswith("p0"):
            raise InvalidResponseError("json non valido")
        return [Edit(original="esinto", corrected="estinto")]

    result = correct_transcript(transcript, corrector=corrector, max_words=4)

    assert result.failed_chunks == [10.0]
    assert result.interrupted_at is None
    assert result.transcript.text == "ha estinto il credito p0 p1 p2 p3"


def test_correct_transcript_keeps_done_work_when_model_becomes_unavailable() -> None:
    transcript = make_transcript(
        [
            make_segment(list(_words("ha esinto il credito"))),
            make_segment([make_word(f" p{i}", 10.0 + i) for i in range(4)]),
            make_segment([make_word(f" q{i}", 20.0 + i) for i in range(4)]),
        ]
    )
    calls = 0

    def corrector(text: str, context: str) -> list[Edit]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CorrectorUnavailableError("ollama down")
        return [Edit(original="esinto", corrected="estinto")]

    result = correct_transcript(transcript, corrector=corrector, max_words=4)

    assert calls == 2
    assert result.interrupted_at == 10.0
    assert result.transcript.text == "ha estinto il credito p0 p1 p2 p3 q0 q1 q2 q3"
    assert len(result.applied) == 1


def test_apply_edits_chained_edits_keep_what_whisper_heard() -> None:
    words = _words("la lesione degli interessi")

    result = apply_edits(
        words,
        [
            Edit(original="lesione", corrected="legione"),
            Edit(original="legione", corrected="regione"),
        ],
    )

    assert result.words[1].text == " regione"
    assert result.words[1].corrected_from == "lesione"
