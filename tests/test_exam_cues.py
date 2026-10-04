from dataclasses import FrozenInstanceError, replace

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.exam_cues import CueLevel, ExamCue, classify_sentence, find_exam_cues


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "all'esame la classica domanda è la differenza fra nullità e annullabilità",
            "strong",
        ),
        ("io vi chiederò sicuramente i vizi del consenso", "strong"),
        ("ricordatevi che il termine è di cinque anni", "strong"),
        ("segnatevelo", "strong"),
        ("questa è una domanda d'esame", "strong"),
        ("questo lo chiedo", "strong"),
        ("questo è importante", "weak"),
        ("è fondamentale", "weak"),
        ("attenzione al gradino", "weak"),
        ("VI CHIEDERÒ questo", "strong"),
        ("ALL’ESAME torna spesso", "strong"),
        ("è importante, ricordatevi questo", "strong"),
        ("l'importante è che capiate, perché all'esame lo chiedo", "strong"),
        ("l'importante è che ricordatevi sia chiaro", "strong"),
    ],
)
def test_classify_sentence_signals_match_level(text: str, expected: CueLevel) -> None:
    assert classify_sentence(text=text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "l'importante è che abbiate capito",
        "l’importante è che abbiate capito",
        "per disattenzione ho saltato un passaggio",
        "glielo chiedo domani",
        "gli importanti autori del periodo",
        "la lezione finisce qui",
        "",
    ],
)
def test_classify_sentence_exclusions_return_none(text: str) -> None:
    assert classify_sentence(text="questo è importante") == "weak"
    assert classify_sentence(text=text) is None


def test_find_exam_cues_three_segments_preserve_segment_start() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(words=[make_word(text="Oggi parliamo di diritto", start=0.0)]),
            make_segment(words=[make_word(text="Ricordatevi il termine", start=12.5)]),
            make_segment(words=[make_word(text="Questo è importante", start=35.0)]),
        ]
    )

    cues = find_exam_cues(transcript=transcript, job_id="lecture")

    assert cues == (
        ExamCue(
            job_id="lecture",
            segment_index=1,
            quote="Ricordatevi il termine",
            start=12.5,
            level="strong",
        ),
        ExamCue(
            job_id="lecture",
            segment_index=2,
            quote="Questo è importante",
            start=35.0,
            level="weak",
        ),
    )


def test_find_exam_cues_splits_sentences_in_reading_order() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[
                    make_word(
                        text="Introduzione. Questo è importante! Ricordatevi il termine? Segnatevelo...",
                        start=9.25,
                    )
                ]
            )
        ]
    )

    cues = find_exam_cues(transcript=transcript, job_id="lecture")

    assert [(cue.quote, cue.level) for cue in cues] == [
        ("Questo è importante", "weak"),
        ("Ricordatevi il termine", "strong"),
        ("Segnatevelo", "strong"),
    ]
    assert [(cue.start, cue.segment_index) for cue in cues] == [(9.25, 0)] * 3


def test_find_exam_cues_inner_dots_keep_sentence_whole() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[
                    make_word(
                        text="All'esame vi chiederò l'art.1140 c.c. sul possesso. Fine.",
                        start=4.0,
                    )
                ]
            )
        ]
    )

    cues = find_exam_cues(transcript=transcript, job_id="lecture")

    assert [cue.quote for cue in cues] == ["All'esame vi chiederò l'art.1140 c.c"]


def test_find_exam_cues_negative_context_stays_within_sentence() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[
                    make_word(
                        text="l'importante è che abbiate capito. All'esame lo chiedo",
                        start=0.0,
                    )
                ]
            )
        ]
    )

    cues = find_exam_cues(transcript=transcript, job_id="lecture")

    assert len(cues) == 1
    assert cues[0].quote == "All'esame lo chiedo"
    assert cues[0].level == "strong"


def test_find_exam_cues_empty_transcript_returns_tuple() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[
                    make_word(
                        text="Segnatevelo",
                        start=0.0,
                    )
                ]
            )
        ]
    )
    assert len(find_exam_cues(transcript=transcript, job_id="lecture")) == 1
    assert (
        find_exam_cues(transcript=replace(transcript, segments=()), job_id="lecture")
        == ()
    )


@pytest.mark.parametrize("quote", ["", "   "])
def test_exam_cue_empty_quote_raises_value_error(quote: str) -> None:
    cue = ExamCue(
        job_id="lecture",
        segment_index=0,
        quote="Segnatevelo",
        start=0.0,
        level="strong",
    )
    with pytest.raises(ValueError, match="quote"):
        replace(cue, quote=quote)


def test_exam_cue_negative_start_raises_value_error() -> None:
    cue = ExamCue(
        job_id="lecture",
        segment_index=0,
        quote="Segnatevelo",
        start=0.0,
        level="strong",
    )
    with pytest.raises(ValueError, match="start"):
        replace(cue, start=-1.0)


def test_exam_cue_is_frozen() -> None:
    cue = ExamCue(
        job_id="lecture",
        segment_index=0,
        quote="Segnatevelo",
        start=0.0,
        level="strong",
    )
    with pytest.raises(FrozenInstanceError):
        cue.__setattr__("quote", "changed")
