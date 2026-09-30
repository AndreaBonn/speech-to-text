from pathlib import Path

from conftest import make_segment, make_transcript, make_word

from sbobina.models import load_transcript, save_transcript


def test_segment_text_joins_whisper_word_prefixes() -> None:
    segment = make_segment(
        [make_word(" Oggi", 0.0), make_word(" dell", 0.5), make_word("'equazione", 0.9)]
    )

    assert segment.text == "Oggi dell'equazione"


def test_save_then_load_transcript_roundtrips_all_fields(tmp_path: Path) -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(" Perché", 0.0, 0.42)]),
            make_segment([make_word(" è", 3.0, 0.97)]),
        ]
    )
    path = tmp_path / "t.json"

    save_transcript(transcript, path)

    assert load_transcript(path) == transcript
    assert "Perché" in path.read_text(encoding="utf-8")


def test_load_transcript_accepts_files_written_before_corrected_from(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.json"
    path.write_text(
        '{"source": "a.m4a", "model": "large-v3", "language": "it", "duration": 1.0,'
        ' "segments": [{"start": 0.0, "end": 1.0, "words":'
        ' [{"start": 0.0, "end": 1.0, "text": " ciao", "probability": 0.9}]}]}',
        encoding="utf-8",
    )

    assert load_transcript(path).words[0].corrected_from is None
