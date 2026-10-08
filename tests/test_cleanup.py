from conftest import make_segment, make_transcript, make_word

from sbobina.cleanup import remove_silence_fillers
from sbobina.models import Word


def _seg(text: str, start: float) -> list[Word]:
    return [make_word(f" {text}", start)]


def test_removes_grazie_followed_by_long_pause() -> None:
    transcript = make_transcript(
        [
            make_segment(_seg("prove", 0.0)),
            make_segment(_seg("Grazie.", 0.5)),
            make_segment(_seg("Riprendiamo", 30.0)),
        ]
    )

    cleaned, removed = remove_silence_fillers(transcript)

    assert [s.text for s in cleaned.segments] == ["prove", "Riprendiamo"]
    assert [s.text for s in removed] == ["Grazie."]


def test_removes_grazie_at_end_after_long_pause() -> None:
    transcript = make_transcript(
        [make_segment(_seg("quale?", 0.0)), make_segment(_seg("grazie", 25.0))]
    )

    cleaned, removed = remove_silence_fillers(transcript)

    assert [s.text for s in cleaned.segments] == ["quale?"]
    assert len(removed) == 1


def test_keeps_grazie_inside_continuous_speech() -> None:
    transcript = make_transcript(
        [
            make_segment(_seg("conosciuta", 0.0)),
            make_segment(_seg("grazie", 0.4)),
            make_segment(_seg("allora", 0.8)),
        ]
    )

    cleaned, removed = remove_silence_fillers(transcript)

    assert removed == []
    assert cleaned == transcript


def test_keeps_longer_sentence_containing_grazie_next_to_pause() -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(" Grazie", 0.0), make_word(" della", 0.4)]),
            make_segment(_seg("domanda", 40.0)),
        ]
    )

    cleaned, removed = remove_silence_fillers(transcript)

    assert removed == []
    assert cleaned == transcript


def test_grazie_with_pause_exactly_at_threshold_is_removed() -> None:
    transcript = make_transcript(
        [
            make_segment(_seg("prove", 0.0)),
            make_segment(_seg("Grazie.", 0.5)),
            make_segment(_seg("Riprendiamo", 0.9 + 10.0)),
        ]
    )

    _, removed = remove_silence_fillers(transcript)

    assert [s.text for s in removed] == ["Grazie."]


def test_grazie_with_pause_just_below_threshold_is_kept() -> None:
    transcript = make_transcript(
        [
            make_segment(_seg("prove", 0.0)),
            make_segment(_seg("Grazie.", 0.5)),
            make_segment(_seg("Riprendiamo", 0.9 + 9.9)),
        ]
    )

    cleaned, removed = remove_silence_fillers(transcript)

    assert removed == []
    assert cleaned == transcript
