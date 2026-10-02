from collections import Counter
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace

from sbobina.models import Segment
from sbobina.study_citations import validate_item
from sbobina.study_models import (
    Citation,
    ConceptItem,
    ProposedChapter,
    ProposedCitation,
    QuestionItem,
    Rejection,
    RejectionReason,
    StudyChapter,
    StudyItem,
    SummaryItem,
    ValidatedItem,
)


@dataclass(frozen=True)
class _CitationContext:
    segments: Sequence[Segment]
    allowed: AbstractSet[int]
    original: Sequence[Segment] | None


def _citations(proposed: list[ProposedCitation]) -> tuple[Citation, ...]:
    return tuple(
        Citation(segment_index=c.segment_index, quote=c.quote) for c in proposed
    )


def convert_chapter(proposed: ProposedChapter) -> StudyChapter:
    return StudyChapter(
        title=proposed.title,
        start=proposed.start,
        summary=tuple(
            SummaryItem(text=i.text, citations=_citations(proposed=i.citations))
            for i in proposed.summary
        ),
        concepts=tuple(
            ConceptItem(
                term=i.term,
                explanation=i.explanation,
                citations=_citations(proposed=i.citations),
            )
            for i in proposed.concepts
        ),
        questions=tuple(
            QuestionItem(
                question=i.question, citations=_citations(proposed=i.citations)
            )
            for i in proposed.questions
        ),
    )


def _validate_grounded_item(
    item: StudyItem, context: _CitationContext
) -> ValidatedItem | Rejection:
    validated = validate_item(
        segments=context.segments, item=item, allowed=context.allowed
    )
    if isinstance(validated, Rejection) or context.original is None:
        return validated
    persisted = validate_item(
        segments=context.original, item=item, allowed=context.allowed
    )
    if isinstance(persisted, Rejection):
        return persisted
    # Persisted citations cannot distinguish repeated occurrences inside one passage.
    if tuple(c.timestamp for c in validated.citations) != tuple(
        c.timestamp for c in persisted.citations
    ):
        return Rejection(reason=RejectionReason.AMBIGUOUS_QUOTE)
    return validated


def _filter_items[T: StudyItem](
    items: tuple[T, ...], context: _CitationContext
) -> tuple[tuple[T, ...], list[float], Counter[RejectionReason]]:
    kept = []
    starts: list[float] = []
    counts: Counter[RejectionReason] = Counter()
    for item in items:
        validated = _validate_grounded_item(item=item, context=context)
        if isinstance(validated, Rejection):
            counts[validated.reason] += 1
        else:
            kept.append(item)
            starts.extend(c.timestamp for c in validated.citations)
    return tuple(kept), starts, counts


def validate_chapter(
    chapter: StudyChapter,
    segments: Sequence[Segment],
    allowed: AbstractSet[int],
    original: Sequence[Segment] | None = None,
) -> tuple[StudyChapter | None, Counter[RejectionReason]]:
    context = _CitationContext(segments=segments, allowed=allowed, original=original)
    summary, summary_starts, summary_counts = _filter_items(
        items=chapter.summary, context=context
    )
    concepts, concept_starts, concept_counts = _filter_items(
        items=chapter.concepts, context=context
    )
    questions, question_starts, question_counts = _filter_items(
        items=chapter.questions, context=context
    )
    starts = summary_starts + concept_starts + question_starts
    counts = summary_counts + concept_counts + question_counts
    if not starts:
        return None, counts
    return replace(
        chapter,
        start=min(starts),
        summary=summary,
        concepts=concepts,
        questions=questions,
    ), counts
