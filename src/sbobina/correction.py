from collections.abc import Callable
from dataclasses import dataclass, field, replace

from sbobina.edits import AppliedCorrection, Edit, EditResult, RejectedEdit, apply_edits
from sbobina.models import Segment, Transcript

__all__ = [
    "CorrectionResult",
    "Corrector",
    "CorrectorError",
    "CorrectorUnavailableError",
    "Edit",
    "InvalidResponseError",
    "apply_edits",
    "chunk_segments",
    "correct_transcript",
]

Corrector = Callable[[str, str], list[Edit]]


class CorrectorError(Exception):
    """Base class for failures of a ``Corrector``."""


class InvalidResponseError(CorrectorError):
    """The model answered, but not with usable edits: skip this chunk only."""


class CorrectorUnavailableError(CorrectorError):
    """The model cannot be reached: stop, keeping the chunks already corrected."""


@dataclass(frozen=True)
class CorrectionResult:
    transcript: Transcript
    applied: list[AppliedCorrection]
    rejected: list[RejectedEdit]
    failed_chunks: list[float] = field(default_factory=list)  # start times
    interrupted_at: float | None = None


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


def _correct_chunk(
    chunk: list[Segment], corrector: Corrector, context: str
) -> tuple[list[Segment], EditResult]:
    words = tuple(word for segment in chunk for word in segment.words)
    text = " ".join(segment.text for segment in chunk)
    result = apply_edits(words, corrector(text, context))
    return _rebuild_segments(chunk, result), result


def correct_transcript(
    transcript: Transcript, corrector: Corrector, max_words: int
) -> CorrectionResult:
    """Send each chunk (with the previous corrected chunk as context) to ``corrector``.

    A chunk with an invalid model response is kept as is and recorded; if the
    model becomes unavailable, the rest is kept uncorrected and the stop recorded.
    """
    segments: list[Segment] = []
    applied: list[AppliedCorrection] = []
    rejected: list[RejectedEdit] = []
    failed: list[float] = []
    context = ""
    chunks = chunk_segments(transcript.segments, max_words=max_words)
    for index, chunk in enumerate(chunks):
        try:
            corrected_chunk, result = _correct_chunk(chunk, corrector, context)
        except InvalidResponseError:
            failed.append(chunk[0].start)
            corrected_chunk, result = chunk, apply_edits((), [])
        except CorrectorUnavailableError:
            remaining = tuple(s for rest in chunks[index:] for s in rest)
            final = replace(transcript, segments=(*segments, *remaining))
            return CorrectionResult(final, applied, rejected, failed, chunk[0].start)
        segments += corrected_chunk
        applied += result.applied
        rejected += result.rejected
        context = " ".join(segment.text for segment in corrected_chunk)
    final = replace(transcript, segments=tuple(segments))
    return CorrectionResult(final, applied, rejected, failed)
