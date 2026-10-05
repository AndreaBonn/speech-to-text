from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.models import (
    load_transcript,
    save_transcript,
    transcript_from_json,
    transcript_to_json,
)


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


def test_transcript_from_json_round_trips_saved_text() -> None:
    transcript = make_transcript(
        [make_segment([make_word(" uno", 0.0), make_word(" due", 0.4)])]
    )

    assert transcript_from_json(transcript_to_json(transcript)) == transcript


@pytest.mark.parametrize("content", ["{}", '{"segments": null}'])
def test_transcript_from_json_missing_keys_raises_value_error(content: str) -> None:
    with pytest.raises(ValueError, match="Transcript"):
        transcript_from_json(content=content)


def test_save_transcript_replaces_the_file_atomically(tmp_path: Path) -> None:
    # F12 review: the parse cache keys on the inode, so a save must never
    # rewrite in place (and a reader must never see half a file).
    path = tmp_path / "audio.json"
    transcript = make_transcript(
        segments=[make_segment(words=[make_word(text="uno", start=0.0)])]
    )
    save_transcript(transcript=transcript, path=path)
    before = path.stat().st_ino

    save_transcript(transcript=transcript, path=path)

    assert path.stat().st_ino != before
    assert load_transcript(path=path) == transcript
    assert sorted(p.name for p in tmp_path.iterdir()) == ["audio.json"]
