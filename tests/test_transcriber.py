from types import SimpleNamespace

import numpy as np

from sbobina.models import Word
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
