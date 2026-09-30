from collections.abc import Callable
from dataclasses import dataclass, replace

from sbobina.edits import AppliedCorrection, Edit, EditResult, RejectedEdit, apply_edits
from sbobina.models import Segment, Transcript

__all__ = [
    "CorrectionResult",
    "Corrector",
    "Edit",
    "apply_edits",
    "chunk_segments",
    "correct_transcript",
]

Corrector = Callable[[str, str], list[Edit]]


@dataclass(frozen=True)
class CorrectionResult:
    transcript: Transcript
    applied: list[AppliedCorrection]
    rejected: list[RejectedEdit]


def chunk_segments(
    segments: tuple[Segment, ...], max_words: int
) -> list[list[Segment]]:
    chunks: list[list[Segment]] = []
    count = 0
    for segment in segments:
        if chunks and count + len(segment.words) <= max_words:
            chunks[-1].append(segment)
            count += len(segment.words)
        else:
            chunks.append([segment])
            count = len(segment.words)
    return chunks


def _rebuild_segments(chunk: list[Segment], result: EditResult) -> list[Segment]:
    owners = [index for index, segment in enumerate(chunk) for _ in segment.words]
    rebuilt = []
    for index, segment in enumerate(chunk):
        words = tuple(
            w for w, src in zip(result.words, result.sources) if owners[src] == index
        )
        # A merged word can absorb the next segment's words: the segment then
        # vanishes and its time range moves into this one's end.
        if words:
            rebuilt.append(
                replace(segment, words=words, end=max(segment.end, words[-1].end))
            )
    return rebuilt


def correct_transcript(
    transcript: Transcript, corrector: Corrector, max_words: int
) -> CorrectionResult:
    """Send each chunk (with the previous corrected chunk as context) to ``corrector``."""
    segments: list[Segment] = []
    applied: list[AppliedCorrection] = []
    rejected: list[RejectedEdit] = []
    context = ""
    for chunk in chunk_segments(transcript.segments, max_words=max_words):
        words = tuple(word for segment in chunk for word in segment.words)
        text = " ".join(segment.text for segment in chunk)
        result = apply_edits(words, corrector(text, context))
        corrected_chunk = _rebuild_segments(chunk, result)
        segments += corrected_chunk
        applied += result.applied
        rejected += result.rejected
        context = " ".join(segment.text for segment in corrected_chunk)
    return CorrectionResult(
        replace(transcript, segments=tuple(segments)), applied, rejected
    )
