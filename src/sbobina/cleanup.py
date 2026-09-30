from dataclasses import replace

from sbobina.models import Segment, Transcript

# Whisper fills real silences with these phrases in Italian. Measured on an
# 85-min lecture: 5 of 6 isolated "Grazie." sat next to pauses of 24-43 s,
# while 95% of inter-segment pauses are under 2.5 s.
SILENCE_FILLERS = frozenset({"grazie"})
FILLER_PAUSE_S = 10.0


def _is_filler(segment: Segment) -> bool:
    return segment.text.strip(" .,!?").lower() in SILENCE_FILLERS


def _pause_around(segments: tuple[Segment, ...], index: int) -> float:
    before = (
        segments[index].start - segments[index - 1].end if index > 0 else float("inf")
    )
    is_last = index + 1 == len(segments)
    after = float("inf") if is_last else segments[index + 1].start - segments[index].end
    return max(before, after)


def remove_silence_fillers(transcript: Transcript) -> tuple[Transcript, list[Segment]]:
    """Drop filler-only segments that sit next to a long pause.

    Returns
    -------
    tuple[Transcript, list[Segment]]
        The cleaned transcript and the removed segments, for the report.
    """
    segments = transcript.segments
    removed = [
        segment
        for index, segment in enumerate(segments)
        if _is_filler(segment) and _pause_around(segments, index) >= FILLER_PAUSE_S
    ]
    kept = tuple(segment for segment in segments if segment not in removed)
    return replace(transcript, segments=kept), removed
