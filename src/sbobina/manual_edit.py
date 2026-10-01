import re
from dataclasses import replace

from sbobina.edits import EDGE_PUNCTUATION, heard_text
from sbobina.models import Segment, Transcript, Word

# The user listened and typed the words: they are no longer in doubt.
USER_CONFIRMED_PROBABILITY = 1.0
_LEADING = re.compile(r"^\s*")


class InvalidSpanError(ValueError):
    """The word range does not exist in the transcript."""


class EditConflictError(ValueError):
    """The span no longer holds the text the user was looking at."""


def _correction(typed: str, heard: str) -> str | None:
    return None if typed.strip(EDGE_PUNCTUATION) == heard else heard


def _same_count_words(old: tuple[Word, ...], tokens: list[str]) -> list[Word]:
    # One-to-one: every word keeps its own timing and its own Whisper hearing.
    return [
        replace(
            word,
            text=token,
            probability=USER_CONFIRMED_PROBABILITY,
            corrected_from=_correction(typed=token, heard=heard_text((word,))),
        )
        for word, token in zip(old, tokens, strict=True)
    ]


def _respread_words(old: tuple[Word, ...], tokens: list[str]) -> list[Word]:
    # No word-level alignment exists, so time is split evenly over the span and
    # the whole heard phrase is attached to the first new word.
    start, end = old[0].start, old[-1].end
    step = (end - start) / len(tokens)
    heard = heard_text(old)
    typed = " ".join(token.strip() for token in tokens)
    return [
        Word(
            start=start + index * step,
            end=start + (index + 1) * step,
            text=token,
            probability=USER_CONFIRMED_PROBABILITY,
            corrected_from=_correction(typed=typed, heard=heard)
            if index == 0
            else None,
        )
        for index, token in enumerate(tokens)
    ]


def _new_words(old: tuple[Word, ...], text: str) -> list[Word]:
    parts = text.split()
    if not parts:
        return []
    leading = _LEADING.match(old[0].text)
    first_space = leading.group() if leading else ""
    tokens = [first_space + parts[0], *(f" {part}" for part in parts[1:])]
    if len(tokens) == len(old):
        return _same_count_words(old=old, tokens=tokens)
    return _respread_words(old=old, tokens=tokens)


def _rebuild_segments(
    segments: tuple[Segment, ...], start: int, end: int, new_words: list[Word]
) -> tuple[Segment, ...]:
    rebuilt: list[Segment] = []
    offset = 0
    for segment in segments:
        kept: list[Word] = []
        for index, word in enumerate(segment.words, start=offset):
            if index == start:
                kept.extend(new_words)
            if not start <= index < end:
                kept.append(word)
        touched = offset < end and start < offset + len(segment.words)
        offset += len(segment.words)
        if not kept:
            continue
        if touched:
            # Bounds follow the words, or a stale end would hide a pause from
            # the paragraph grouping.
            segment = replace(segment, start=kept[0].start, end=kept[-1].end)
        rebuilt.append(replace(segment, words=tuple(kept)))
    return tuple(rebuilt)


def replace_span(
    transcript: Transcript, start: int, end: int, text: str, expected: str
) -> Transcript:
    """Replace words ``[start, end)`` with the text the user typed.

    Parameters
    ----------
    transcript : Transcript
        The transcript being edited; it is not modified.
    start, end : int
        Flat word indices, end exclusive.
    text : str
        Replacement; blank deletes the span.
    expected : str
        The span's text as the user saw it, compared ignoring outer spaces.

    Returns
    -------
    Transcript
        A new transcript; segments left without words are dropped.

    Raises
    ------
    InvalidSpanError
        If the range is empty or outside the transcript.
    EditConflictError
        If the span's current text differs from ``expected``.
    """
    words = transcript.words
    if not 0 <= start < end <= len(words):
        raise InvalidSpanError(f"Intervallo di parole non valido: {start}-{end}")
    old = words[start:end]
    if "".join(word.text for word in old).strip() != expected.strip():
        raise EditConflictError("Il testo selezionato è cambiato nel frattempo")
    new_words = _new_words(old=old, text=text)
    segments = _rebuild_segments(
        segments=transcript.segments, start=start, end=end, new_words=new_words
    )
    return replace(transcript, segments=segments)
