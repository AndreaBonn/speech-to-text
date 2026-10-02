import math
import re
from dataclasses import dataclass, replace

from sbobina.models import Segment, Transcript, Word
from sbobina.render import format_timestamp

PAUSE_WINDOW_FRACTION = 0.2


def study_timestamp(seconds: float) -> str:
    return format_timestamp(seconds=seconds).removeprefix("00:")


@dataclass(frozen=True)
class StudyBlock:
    segments: tuple[Segment, ...]
    allowed: frozenset[int]
    start: float
    end: float

    @property
    def text(self) -> str:
        return "\n".join(
            f"[S{index}] {study_timestamp(self.segments[index].start)} "
            f"{self.segments[index].text}"
            for index in sorted(self.allowed)
        )


def _token_words(segment: Segment) -> tuple[Word, ...]:
    text = "".join(word.text for word in segment.words)
    owners = [word for word in segment.words for _ in word.text]
    return tuple(
        replace(
            owners[match.start()],
            text=" " + match.group(),
            end=owners[match.end() - 1].end,
        )
        for match in re.finditer(r"\S+", text)
    )


def _block_end(words: list[tuple[int, Word]], start: int, max_words: int) -> int:
    end = min(start + max_words, len(words))
    if end == len(words):
        return end
    window = start + max(1, math.ceil(max_words * (1 - PAUSE_WINDOW_FRACTION)))
    return max(
        range(window, end + 1),
        key=lambda index: (words[index][1].start - words[index - 1][1].end, index),
    )


def _make_block(
    segments: tuple[Segment, ...], words: list[tuple[int, Word]]
) -> StudyBlock:
    grouped: dict[int, list[Word]] = {}
    for index, word in words:
        grouped.setdefault(index, []).append(word)
    visible = tuple(
        replace(
            segment,
            words=tuple(grouped.get(index, ())),
            start=grouped[index][0].start if index in grouped else segment.start,
            end=grouped[index][-1].end if index in grouped else segment.end,
        )
        for index, segment in enumerate(segments)
    )
    return StudyBlock(
        segments=visible,
        allowed=frozenset(grouped),
        start=words[0][1].start,
        end=words[-1][1].end,
    )


def build_study_blocks(
    transcript: Transcript, max_words: int
) -> tuple[StudyBlock, ...]:
    """Split on the longest pause in the final fifth, preserving passage indices."""
    if max_words <= 0:
        raise ValueError("max_words must be positive")
    words = [
        (index, word)
        for index, segment in enumerate(transcript.segments)
        for word in _token_words(segment=segment)
    ]
    blocks = []
    start = 0
    while start < len(words):
        end = _block_end(words=words, start=start, max_words=max_words)
        blocks.append(_make_block(segments=transcript.segments, words=words[start:end]))
        start = end
    return tuple(blocks)
