import pytest
from pydantic import ValidationError

from sbobina.assemblyai_mapping import TranscriptMeta, to_transcript
from sbobina.models import Segment

META = TranscriptMeta(
    source="lezione.m4a", speech_model="universal-3-5-pro", language="it", duration=9.5
)


def _word(
    text: str, start: int, end: int, confidence: float = 0.98
) -> dict[str, object]:
    return {"text": text, "start": start, "end": end, "confidence": confidence}


def _sentences() -> dict[str, object]:
    return {
        "sentences": [
            {
                "text": "Buongiorno a tutti.",
                "start": 0,
                "end": 1640,
                "words": [
                    _word("Buongiorno", 0, 640),
                    _word("a", 700, 800),
                    _word("tutti.", 820, 1640, confidence=0.42),
                ],
            },
            {
                "text": "Oggi entropia.",
                "start": 4140,
                "end": 5200,
                "words": [_word("Oggi", 4140, 4500), _word("entropia.", 4520, 5200)],
            },
        ]
    }


def test_to_transcript_maps_sentences_to_segments_in_seconds() -> None:
    transcript = to_transcript(payload=_sentences(), meta=META)

    assert len(transcript.segments) == 2
    first: Segment = transcript.segments[0]
    assert (first.start, first.end) == (0.0, 1.64)
    assert first.text == "Buongiorno a tutti."
    assert transcript.segments[1].start == 4.14


def test_to_transcript_keeps_confidence_and_whisper_word_spacing() -> None:
    words = to_transcript(payload=_sentences(), meta=META).words

    assert words[0].text == " Buongiorno"
    assert words[2].probability == 0.42


def test_to_transcript_records_engine_model_and_language() -> None:
    transcript = to_transcript(payload=_sentences(), meta=META)

    assert transcript.model == "assemblyai:universal-3-5-pro"
    assert transcript.language == "it"
    assert transcript.duration == 9.5
    assert transcript.source == "lezione.m4a"


def test_to_transcript_drops_sentences_without_words() -> None:
    payload = {"sentences": [{"text": "", "start": 0, "end": 10, "words": []}]}

    assert to_transcript(payload=payload, meta=META).segments == ()


def test_to_transcript_word_without_confidence_is_rejected() -> None:
    payload = {
        "sentences": [
            {
                "text": "x",
                "start": 0,
                "end": 1,
                "words": [{"text": "x", "start": 0, "end": 1}],
            }
        ]
    }

    with pytest.raises(ValidationError):
        to_transcript(payload=payload, meta=META)
