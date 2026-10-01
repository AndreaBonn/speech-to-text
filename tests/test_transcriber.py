from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import faster_whisper
import numpy as np
import pytest

from sbobina import transcriber
from sbobina.models import Word
from sbobina.settings import Settings
from sbobina.transcriber import to_segment


def test_to_segment_converts_numpy_floats_and_keeps_word_text() -> None:
    raw = SimpleNamespace(
        start=np.float64(1.0),
        end=np.float64(2.0),
        words=[
            SimpleNamespace(
                start=1.0, end=1.5, word=" Noether", probability=np.float64(0.67)
            )
        ],
    )

    segment = to_segment(raw)

    assert segment is not None
    assert segment.words == (
        Word(start=1.0, end=1.5, text=" Noether", probability=0.67),
    )
    assert type(segment.words[0].probability) is float


def test_to_segment_without_words_returns_none() -> None:
    raw = SimpleNamespace(start=0.0, end=1.0, words=None)

    assert to_segment(raw) is None


def test_transcribe_file_passes_vad_setting_to_whisper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def transcribe(
            self, audio: str, **kwargs: object
        ) -> tuple[list[object], object]:
            captured.update(kwargs)
            return [], SimpleNamespace(duration=0.0)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber, "preload_cuda_libraries", list)

    transcriber.transcribe_file(tmp_path / "a.m4a", Settings(vad_filter=False))

    assert captured["vad_filter"] is False
    assert captured["word_timestamps"] is True


@pytest.mark.parametrize("track_progress", [True, False])
def test_transcribe_file_empty_segment_advances_progress(
    tmp_path: Path, track_progress: bool
) -> None:
    calls: list[tuple[float, float]] = []
    raw_segments = [
        SimpleNamespace(start=0.0, end=10.0, words=None),
        SimpleNamespace(
            start=10.0,
            end=30.0,
            words=[
                SimpleNamespace(start=10.0, end=30.0, word=" ciao", probability=0.9)
            ],
        ),
    ]
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = (
            raw_segments,
            SimpleNamespace(duration=30.0),
        )
        if track_progress:
            result = transcriber.transcribe_file(
                tmp_path / "a.m4a",
                config=Settings(),
                on_progress=lambda end, duration: calls.append((end, duration)),
            )
        else:
            result = transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings())

    assert result.text == "ciao"
    assert calls == ([(10.0, 30.0), (30.0, 30.0)] if track_progress else [])


def test_collect_segments_default_callback_preserves_segments() -> None:
    raw = SimpleNamespace(
        start=0.0,
        end=10.0,
        words=[SimpleNamespace(start=0.0, end=10.0, word=" ciao", probability=0.9)],
    )

    segments = transcriber._collect_segments([raw], duration=10.0)

    assert len(segments) == 1
    assert segments[0].text == "ciao"
