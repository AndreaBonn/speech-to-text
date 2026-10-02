import sys
from collections.abc import Iterator

import pytest

from sbobina.models import Segment, Transcript, Word


def make_word(text: str, start: float, probability: float = 0.99) -> Word:
    return Word(start=start, end=start + 0.4, text=text, probability=probability)


def make_segment(words: list[Word]) -> Segment:
    return Segment(start=words[0].start, end=words[-1].end, words=tuple(words))


def make_transcript(segments: list[Segment]) -> Transcript:
    return Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=segments[-1].end,
        segments=tuple(segments),
    )


@pytest.fixture(autouse=True)
def _keep_process_memory_limit() -> Iterator[None]:
    """Fail any test that lowers RLIMIT_AS of the pytest process itself.

    The limit cannot be raised again, so one such test leaves every later test
    unable to start threads or map memory: the suite hangs instead of failing.
    """
    if sys.platform == "win32":
        yield
        return
    import resource

    before = resource.getrlimit(resource.RLIMIT_AS)
    yield
    after = resource.getrlimit(resource.RLIMIT_AS)
    assert after == before, f"test changed RLIMIT_AS of pytest: {before} -> {after}"
