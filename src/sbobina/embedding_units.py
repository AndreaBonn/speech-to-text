import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sbobina.lecture_windows import partition_lecture_segments
from sbobina.retrieval_metrics import DocumentRef, LectureRef
from sbobina.search_text import Passage


@dataclass(frozen=True)
class DocUnit:
    passage_id: str
    text: str
    ref: DocumentRef


@dataclass(frozen=True)
class LectureUnit:
    passage_id: str
    text: str
    ref: LectureRef


EvalUnit = DocUnit | LectureUnit


def content_hash(text: str) -> str:
    """Stable cache key for one unit's text, independent of its passage_id."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def segment_positions(segments: Sequence[Passage]) -> dict[int, int]:
    """Map each Passage.segment_index to its position in `segments`.

    passages_from_transcript drops empty-text segments, so segment_index (the
    original transcript position) and the list position diverge once a gap
    happened upstream: this is the join key a raw BM25 hit needs to find the
    window that contains it.
    """
    return {
        passage.segment_index: position for position, passage in enumerate(segments)
    }


def build_lecture_units(
    *,
    job_id: str,
    segments: Sequence[Passage],
    segment_ends: Sequence[float],
    window_words: int,
) -> tuple[list[tuple[int, int]], list[LectureUnit]]:
    """Whole-transcript ~window_words windows: the lecture candidate universe.

    Reuses production's partition_lecture_segments. Passage has no end field,
    so segment_ends[i] must come from the same filtered pass as `segments`.
    """
    spans = partition_lecture_segments(
        segments=list(segments), window_words=window_words
    )
    units = [
        LectureUnit(
            passage_id=f"L{job_id}-W{position}",
            text=" ".join(segment.text for segment in segments[first : last + 1]),
            ref=LectureRef(
                job_id=job_id,
                start_s=segments[first].start,
                end_s=segment_ends[last],
            ),
        )
        for position, (first, last) in enumerate(spans)
    ]
    return spans, units


def _window_containing(
    *, spans: Sequence[tuple[int, int]], position: int
) -> int | None:
    for index, (first, last) in enumerate(spans):
        if first <= position <= last:
            return index
    return None


def aggregate_lecture_hits_to_windows(
    *,
    hits: Sequence[tuple[float, int]],
    segment_positions: Mapping[int, int],
    spans: Sequence[tuple[int, int]],
    units: Sequence[LectureUnit],
) -> list[tuple[float, LectureUnit]]:
    """Project raw-segment BM25 hits onto the window units they fall inside.

    A window hit by more than one matched segment keeps the best (lowest,
    ascending-better like bm25()) score. A hit whose segment_index has no
    known position, or whose position falls in no span, is dropped: both are
    data the eval harness could not resolve, not a candidate.
    """
    best: dict[int, float] = {}
    for score, segment_index in hits:
        position = segment_positions.get(segment_index)
        if position is None:
            continue
        window_index = _window_containing(spans=spans, position=position)
        if window_index is None:
            continue
        if window_index not in best or score < best[window_index]:
            best[window_index] = score
    return [(score, units[window_index]) for window_index, score in best.items()]
