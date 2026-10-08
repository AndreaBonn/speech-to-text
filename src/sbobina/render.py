import html
import re
from dataclasses import dataclass
from pathlib import Path

from sbobina.models import Segment, Transcript, Word

CONTEXT_WORDS = 4
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
# Measured 2026-10-08 on data/jobs/82144973-acfa-4b8b-ab8b-90c8ef51e85e
# (85-minute Diritto lecture, job threshold 0.7): at the full threshold 20.7%
# of words are flagged ("Tutte"); halving it to 0.35 keeps only 5.7% flagged,
# a visibly sparser "most doubtful" set without losing the clearest outliers.
MOST_UNCERTAIN_FACTOR = 0.5
# Apostrophes are not trailing punctuation: in Italian a final one is an
# elision ("po'"), part of the word rather than a closing quote.
_WORD_PARTS = re.compile(r"^(\s*)([\"'’“«(\[¿]*)(.*?)([\"”».,;:!?)\]…]*)$", re.DOTALL)


@dataclass(frozen=True)
class RenderOptions:
    uncertain_threshold: float
    paragraph_gap_s: float
    paragraph_max_s: float


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def mark_word(text: str) -> str:
    """Wrap the word body in ``[?…?]``, leaving whitespace and punctuation outside."""
    match = _WORD_PARTS.match(text)
    if match is None or not match.group(3):
        return text
    prefix, leading, body, trailing = match.groups()
    return f"{prefix}{leading}[?{body}?]{trailing}"


def mark_correction(text: str, heard: str) -> str:
    """Show what Whisper heard as a superscript after the corrected word body."""
    match = _WORD_PARTS.match(text)
    if match is None or not match.group(3):
        return text
    prefix, leading, body, trailing = match.groups()
    return f"{prefix}{leading}{body}<sup>{html.escape(heard)}</sup>{trailing}"


def _render_word(word: Word, threshold: float) -> str:
    if word.corrected_from is not None:
        return mark_correction(word.text, word.corrected_from)
    return mark_word(word.text) if word.probability < threshold else word.text


def most_uncertain_threshold(threshold: float) -> float:
    """Stricter threshold for the reader's "most doubtful" level.

    Parameters
    ----------
    threshold : float
        The job's own uncertainty threshold ("Tutte" level).

    Returns
    -------
    float
        A threshold always below or equal to ``threshold``, so the "most
        doubtful" set of words is a subset of the full one regardless of
        how the job was configured.
    """
    return threshold * MOST_UNCERTAIN_FACTOR


def find_uncertain_spans(
    words: tuple[Word, ...], threshold: float
) -> list[tuple[int, int]]:
    """Return ``[start, end)`` index ranges of consecutive words below ``threshold``."""
    spans: list[tuple[int, int]] = []
    span_start: int | None = None
    for index, word in enumerate(words):
        if word.probability < threshold and span_start is None:
            span_start = index
        elif word.probability >= threshold and span_start is not None:
            spans.append((span_start, index))
            span_start = None
    if span_start is not None:
        spans.append((span_start, len(words)))
    return spans


def group_paragraphs(
    segments: tuple[Segment, ...], options: RenderOptions
) -> list[list[Segment]]:
    paragraphs: list[list[Segment]] = []
    for segment in segments:
        if paragraphs:
            current = paragraphs[-1]
            is_pause = segment.start - current[-1].end >= options.paragraph_gap_s
            is_too_long = segment.start - current[0].start >= options.paragraph_max_s
            if not (is_pause or is_too_long):
                current.append(segment)
                continue
        paragraphs.append([segment])
    return paragraphs


def _render_paragraph(paragraph: list[Segment], threshold: float) -> str:
    body = "".join(
        _render_word(word, threshold) for segment in paragraph for word in segment.words
    )
    return f"[{format_timestamp(paragraph[0].start)}] {body.strip()}"


def _render_review_item(words: tuple[Word, ...], span: tuple[int, int]) -> str:
    start, end = span
    before = "".join(
        w.text for w in words[max(0, start - CONTEXT_WORDS) : start]
    ).strip()
    flagged = "".join(w.text for w in words[start:end]).strip()
    after = "".join(w.text for w in words[end : end + CONTEXT_WORDS]).strip()
    context = " ".join(part for part in (before, f"**{flagged}**", after) if part)
    return f"- [{format_timestamp(words[start].start)}] … {context} …"


def render_markdown(transcript: Transcript, options: RenderOptions) -> str:
    """Render the reading copy: timestamped paragraphs plus a list of spots to re-listen."""
    words = transcript.words
    spans = find_uncertain_spans(words, options.uncertain_threshold)
    flagged_count = sum(end - start for start, end in spans)
    paragraphs = group_paragraphs(transcript.segments, options)

    lines = [
        f"# Sbobinatura: {Path(transcript.source).name}",
        "",
        (
            f"Modello {transcript.model}, durata {format_timestamp(transcript.duration)}, "
            f"parole incerte: {flagged_count} (soglia {options.uncertain_threshold:.2f})"
        ),
        "",
        *[
            block
            for paragraph in paragraphs
            for block in (_render_paragraph(paragraph, options.uncertain_threshold), "")
        ],
        "## Punti da riascoltare",
        "",
    ]
    if spans:
        lines.extend(_render_review_item(words, span) for span in spans)
    else:
        lines.append("Nessun punto sotto la soglia di confidenza.")
    return "\n".join(lines) + "\n"
