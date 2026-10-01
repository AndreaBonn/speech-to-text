from dataclasses import dataclass

from sbobina.models import Transcript, Word
from sbobina.render import (
    CONTEXT_WORDS,
    RenderOptions,
    find_uncertain_spans,
    group_paragraphs,
)


@dataclass(frozen=True)
class WordView:
    """A timed reader word with uncertainty and its original spelling, if corrected.

    ``index`` is the word's flat position in the transcript, the handle the
    reader sends back when the user edits a span.
    """

    index: int
    start: float
    end: float
    text: str
    uncertain: bool
    corrected_from: str | None


@dataclass(frozen=True)
class ReviewPoint:
    """An uncertain span with its seek time and up to four context words per side."""

    start: float
    before: str
    text: str
    after: str


def _build_word_view(word: Word, index: int, threshold: float) -> WordView:
    return WordView(
        index=index,
        start=word.start,
        end=word.end,
        text=word.text,
        uncertain=word.probability < threshold,
        corrected_from=word.corrected_from,
    )


def build_paragraphs(
    transcript: Transcript, options: RenderOptions
) -> list[list[WordView]]:
    """Map transcript words to reader paragraphs using the Markdown boundaries.

    Parameters
    ----------
    transcript : Transcript
        Timed words to display, including any correction provenance.
    options : RenderOptions
        Uncertainty threshold and paragraph gap and duration limits.

    Returns
    -------
    list[list[WordView]]
        Ordered paragraphs preserving every word and its original whitespace.
    """
    paragraphs: list[list[WordView]] = []
    index = 0
    for paragraph in group_paragraphs(segments=transcript.segments, options=options):
        views: list[WordView] = []
        for word in (word for segment in paragraph for word in segment.words):
            views.append(
                _build_word_view(
                    word=word, index=index, threshold=options.uncertain_threshold
                )
            )
            index += 1
        paragraphs.append(views)
    return paragraphs


def _build_review_point(words: tuple[Word, ...], span: tuple[int, int]) -> ReviewPoint:
    start, end = span
    return ReviewPoint(
        start=words[start].start,
        before="".join(
            word.text for word in words[max(0, start - CONTEXT_WORDS) : start]
        ).strip(),
        text="".join(word.text for word in words[start:end]).strip(),
        after="".join(word.text for word in words[end : end + CONTEXT_WORDS]).strip(),
    )


def build_review_points(transcript: Transcript, threshold: float) -> list[ReviewPoint]:
    """Build re-listen entries using the Markdown renderer's spans and context.

    Parameters
    ----------
    transcript : Transcript
        Transcript whose flattened words supply spans and surrounding context.
    threshold : float
        Words with probability strictly below this value are uncertain.

    Returns
    -------
    list[ReviewPoint]
        Chronological entries with separate, trimmed context and flagged text.
    """
    words = transcript.words
    return [
        _build_review_point(words=words, span=span)
        for span in find_uncertain_spans(words=words, threshold=threshold)
    ]
