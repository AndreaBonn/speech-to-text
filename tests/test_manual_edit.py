from dataclasses import replace

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.manual_edit import (
    USER_CONFIRMED_PROBABILITY,
    EditConflictError,
    InvalidSpanError,
    replace_span,
)
from sbobina.models import Transcript


def _transcript() -> Transcript:
    first = make_segment(
        [
            make_word("Il", 0.0, probability=0.4),
            make_word(" processo", 0.4, probability=0.3),
            make_word(" è", 0.8),
        ]
    )
    second = make_segment([make_word(" un", 2.0), make_word(" fatto.", 2.4)])
    return make_transcript([first, second])


def _texts(transcript: Transcript) -> list[list[str]]:
    return [[w.text for w in segment.words] for segment in transcript.segments]


def test_replace_span_single_word_keeps_timing_and_records_heard() -> None:
    edited = replace_span(
        transcript=_transcript(), start=1, end=2, text="possesso", expected="processo"
    )

    word = edited.words[1]
    assert (word.text, word.start, word.end) == (" possesso", 0.4, 0.8)
    assert word.probability == USER_CONFIRMED_PROBABILITY
    assert word.corrected_from == "processo"


def test_replace_span_more_words_spreads_span_time_evenly() -> None:
    edited = replace_span(
        transcript=_transcript(),
        start=1,
        end=2,
        text="possesso pieno",
        expected="processo",
    )

    first, second = edited.words[1], edited.words[2]
    assert (first.text, second.text) == (" possesso", " pieno")
    assert (first.start, first.end) == pytest.approx((0.4, 0.6))
    assert (second.start, second.end) == pytest.approx((0.6, 0.8))
    assert first.corrected_from == "processo"
    assert second.corrected_from is None
    assert edited.words[3].text == " è"


def test_replace_span_across_segments_moves_words_into_first_segment() -> None:
    edited = replace_span(
        transcript=_transcript(), start=2, end=4, text="era un", expected="è un"
    )

    assert _texts(edited) == [["Il", " processo", " era", " un"], [" fatto."]]
    assert edited.segments[0].end == pytest.approx(2.4)


def test_replace_span_empty_text_deletes_words_and_drops_empty_segment() -> None:
    edited = replace_span(
        transcript=_transcript(), start=3, end=5, text="  ", expected="un fatto."
    )

    assert _texts(edited) == [["Il", " processo", " è"]]


def test_replace_span_keeps_missing_leading_space_of_first_word() -> None:
    edited = replace_span(
        transcript=_transcript(), start=0, end=1, text="Lo", expected="Il"
    )

    assert edited.words[0].text == "Lo"


def test_replace_span_restoring_heard_text_clears_correction() -> None:
    corrected = replace(make_word(" possesso", 0.0), corrected_from="processo")
    transcript = make_transcript([make_segment([corrected])])

    edited = replace_span(
        transcript=transcript, start=0, end=1, text="processo", expected="possesso"
    )

    assert edited.words[0].text == " processo"
    assert edited.words[0].corrected_from is None


def test_replace_span_punctuation_only_change_is_not_a_correction() -> None:
    edited = replace_span(
        transcript=_transcript(), start=2, end=3, text="è,", expected="è"
    )

    assert edited.words[2].text == " è,"
    assert edited.words[2].corrected_from is None


def test_replace_span_untouched_llm_correction_keeps_whisper_hearing() -> None:
    llm_fixed = replace(make_word(" possesso", 0.0), corrected_from="processo")
    transcript = make_transcript([make_segment([llm_fixed, make_word(" è", 0.4)])])

    edited = replace_span(
        transcript=transcript,
        start=0,
        end=2,
        text="possesso era",
        expected="possesso è",
    )

    assert [w.corrected_from for w in edited.words] == ["processo", "è"]


def test_replace_span_stale_expected_text_raises_and_leaves_input() -> None:
    transcript = _transcript()

    with pytest.raises(EditConflictError):
        replace_span(
            transcript=transcript, start=1, end=2, text="possesso", expected="altro"
        )

    assert transcript.words[1].text == " processo"


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (2, 2), (3, 1), (4, 6)])
def test_replace_span_invalid_range_raises(start: int, end: int) -> None:
    with pytest.raises(InvalidSpanError):
        replace_span(
            transcript=_transcript(), start=start, end=end, text="x", expected=""
        )


def test_replace_span_deleting_trailing_words_shrinks_segment_end() -> None:
    edited = replace_span(
        transcript=_transcript(), start=2, end=3, text="", expected="è"
    )

    assert edited.segments[0].end == pytest.approx(0.8)


def test_replace_span_deleting_leading_words_moves_segment_start() -> None:
    edited = replace_span(
        transcript=_transcript(), start=3, end=4, text="", expected="un"
    )

    assert edited.segments[1].start == pytest.approx(2.4)


def test_replace_span_untouched_segment_keeps_its_bounds() -> None:
    edited = replace_span(
        transcript=_transcript(), start=0, end=1, text="Lo", expected="Il"
    )

    assert edited.segments[1] == _transcript().segments[1]
