"""Expand a lecture hit into a window of adjacent segments (ADR D2, T025).

Pure: takes the segments a caller already loaded for every lecture a
question matched (sbobina.web.course_retrieval reads the transcripts) and
grows each lecture hit into a passage of about window_words words instead of
its single 10-30 word Whisper segment. Two windows of the same lecture that
overlap or touch merge into one, kept at the better-ranked position. The
citation (source, passage_id) keeps pointing at the originally matched
segment regardless of how far the window grew. Document hits pass through
unchanged.
"""

from dataclasses import dataclass

from sbobina.retrieval import LectureSource, RetrievedPassage
from sbobina.search_text import Passage

WINDOW_WORDS = 250


def _segment_position(segments: list[Passage], segment_index: int) -> int | None:
    for position, passage in enumerate(segments):
        if passage.segment_index == segment_index:
            return position
    return None


def _grow_window(
    segments: list[Passage], center: int, window_words: int
) -> tuple[int, int]:
    """Span [first, last] around center, alternating sides until the target
    word count is reached or both transcript edges are exhausted."""
    first = last = center
    total = len(segments[center].text.split())
    prefer_right = True
    while total < window_words:
        can_left = first > 0
        can_right = last < len(segments) - 1
        if not can_left and not can_right:
            break
        if can_right and (prefer_right or not can_left):
            last += 1
            total += len(segments[last].text.split())
        else:
            first -= 1
            total += len(segments[first].text.split())
        prefer_right = not prefer_right
    return first, last


def _window_text(segments: list[Passage], first: int, last: int) -> str:
    return " ".join(segment.text for segment in segments[first : last + 1])


def _window_for_hit(
    hit: RetrievedPassage, segments_by_job: dict[str, list[Passage]], window_words: int
) -> tuple[LectureSource, int, int, list[Passage]] | None:
    source = hit.source
    if not isinstance(source, LectureSource):
        return None
    segments = segments_by_job.get(source.job_id)
    if not segments:
        return None
    position = _segment_position(segments=segments, segment_index=source.segment_index)
    if position is None:
        return None
    first, last = _grow_window(
        segments=segments, center=position, window_words=window_words
    )
    return source, first, last, segments


@dataclass(frozen=True)
class _Interval:
    first: int
    last: int
    best_rank: int


def _merge_intervals(intervals: list[_Interval]) -> list[_Interval]:
    """Classic interval merge: sorted by start, touching or overlapping ones
    collapse, so a window bridging two others joins all three."""
    merged: list[_Interval] = []
    for interval in sorted(intervals, key=lambda item: item.first):
        previous = merged[-1] if merged else None
        if previous is not None and interval.first <= previous.last + 1:
            merged[-1] = _Interval(
                first=previous.first,
                last=max(previous.last, interval.last),
                best_rank=min(previous.best_rank, interval.best_rank),
            )
        else:
            merged.append(interval)
    return merged


def _lecture_intervals(
    hits: list[RetrievedPassage],
    segments_by_job: dict[str, list[Passage]],
    window_words: int,
) -> tuple[dict[str, list[_Interval]], dict[int, RetrievedPassage]]:
    """Window intervals per lecture, and the hits that pass through as they are."""
    intervals: dict[str, list[_Interval]] = {}
    unchanged: dict[int, RetrievedPassage] = {}
    for rank, hit in enumerate(hits):
        window = _window_for_hit(
            hit=hit, segments_by_job=segments_by_job, window_words=window_words
        )
        if window is None:
            unchanged[rank] = hit
            continue
        source, first, last, _segments = window
        intervals.setdefault(source.job_id, []).append(
            _Interval(first=first, last=last, best_rank=rank)
        )
    return intervals, unchanged


def expand_lecture_windows(
    hits: list[RetrievedPassage],
    segments_by_job: dict[str, list[Passage]],
    window_words: int = WINDOW_WORDS,
) -> list[RetrievedPassage]:
    """Replace each lecture hit with a ~window_words passage around it."""
    intervals, by_rank = _lecture_intervals(
        hits=hits, segments_by_job=segments_by_job, window_words=window_words
    )
    for job_id, job_intervals in intervals.items():
        segments = segments_by_job[job_id]
        for interval in _merge_intervals(intervals=job_intervals):
            anchor = hits[interval.best_rank]
            by_rank[interval.best_rank] = RetrievedPassage(
                text=_window_text(
                    segments=segments, first=interval.first, last=interval.last
                ),
                source=anchor.source,
                passage_id=anchor.passage_id,
            )
    return [by_rank[rank] for rank in sorted(by_rank)]


def partition_lecture_segments(
    segments: list[Passage], window_words: int
) -> list[tuple[int, int]]:
    """Whole transcript split into consecutive, non-overlapping [first, last] spans.

    Unlike _grow_window (which expands around one matched segment), this
    walks the transcript once from the start: a span closes as soon as it
    reaches window_words, then the next one starts right after it. Used by
    sbobina.web.course_retrieval.sample_course to turn an unmatched lecture
    into citable windows when there is no question to search for.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    total = 0
    for index, segment in enumerate(segments):
        total += len(segment.text.split())
        if total >= window_words:
            spans.append((start, index))
            start = index + 1
            total = 0
    if start < len(segments):
        spans.append((start, len(segments) - 1))
    return spans
