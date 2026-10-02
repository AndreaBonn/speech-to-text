"""Per-item validation and citation resolution for one LLM generation (T033).

Split out of generation_pipeline.py to stay under the file size limit: this
module turns a parsed LLM response into kept GenerationQuestion/SummarySection
items plus a discard count by reason, using source_citations.py to resolve
every citation against the numbered passages. No I/O, no chat call.
"""

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

from sbobina.generation_models import (
    DiscardCount,
    GenerationCitation,
    GenerationQuestion,
    MultipleChoiceResponse,
    ProposedCitation,
    ProposedMultipleChoiceQuestion,
    ProposedSummarySection,
    ProposedSummarySentence,
    ProposedTextQuestion,
    SummaryResponse,
    SummarySection,
    SummarySentence,
    TextQuestionResponse,
)
from sbobina.retrieval import RetrievedPassage
from sbobina.source_citations import (
    DocumentCitation,
    ProposedSourceCitation,
    SourceCitation,
    SourceRejection,
    resolve_citation,
)

MIN_CITATIONS = 1
MAX_CITATIONS = 3


class DiscardReason(StrEnum):
    CITATION_COUNT = "CITATION_COUNT"
    INVALID_OPTIONS = "INVALID_OPTIONS"


def _to_generation_citation(resolved: SourceCitation) -> GenerationCitation:
    if isinstance(resolved.location, DocumentCitation):
        return GenerationCitation(
            passage_id=resolved.passage_id,
            quote=resolved.quote,
            doc_id=resolved.location.doc_id,
            page=resolved.location.page,
            job_id=None,
            timestamp=None,
        )
    return GenerationCitation(
        passage_id=resolved.passage_id,
        quote=resolved.quote,
        doc_id=None,
        page=None,
        job_id=resolved.location.job_id,
        timestamp=resolved.location.timestamp,
    )


def _resolve_citations(
    proposed: Sequence[ProposedCitation],
    passages: Sequence[RetrievedPassage],
    counts: Counter[str],
) -> tuple[GenerationCitation, ...] | None:
    """None discards the whole item: one bad citation voids its solution."""
    if not MIN_CITATIONS <= len(proposed) <= MAX_CITATIONS:
        counts[DiscardReason.CITATION_COUNT] += 1
        return None
    resolved = []
    for citation in proposed:
        result = resolve_citation(
            passages=passages,
            citation=ProposedSourceCitation(
                label=citation.passage, quote=citation.quote
            ),
        )
        if isinstance(result, SourceRejection):
            counts[result.reason] += 1
            return None
        resolved.append(_to_generation_citation(resolved=result))
    return tuple(resolved)


def _has_valid_options(options: Sequence[str]) -> bool:
    return len(set(options)) == len(options) and all(
        option.strip() for option in options
    )


def _validate_mc_question(
    proposed: ProposedMultipleChoiceQuestion,
    passages: Sequence[RetrievedPassage],
    counts: Counter[str],
) -> GenerationQuestion | None:
    if not _has_valid_options(proposed.options):
        counts[DiscardReason.INVALID_OPTIONS] += 1
        return None
    citations = _resolve_citations(
        proposed=proposed.citations, passages=passages, counts=counts
    )
    if citations is None:
        return None
    return GenerationQuestion(
        question=proposed.question,
        options=tuple(proposed.options),
        correct_index=proposed.correct_index,
        solution=proposed.solution,
        citations=citations,
    )


def _validate_text_question(
    proposed: ProposedTextQuestion,
    passages: Sequence[RetrievedPassage],
    counts: Counter[str],
) -> GenerationQuestion | None:
    citations = _resolve_citations(
        proposed=proposed.citations, passages=passages, counts=counts
    )
    if citations is None:
        return None
    return GenerationQuestion(
        question=proposed.question,
        options=(),
        correct_index=None,
        solution=proposed.solution,
        citations=citations,
    )


def validate_exam_response(
    response: MultipleChoiceResponse | TextQuestionResponse,
    passages: Sequence[RetrievedPassage],
) -> tuple[tuple[GenerationQuestion, ...], Counter[str]]:
    counts: Counter[str] = Counter()
    questions = []
    for proposed in response.questions:
        validated = (
            _validate_mc_question(proposed=proposed, passages=passages, counts=counts)
            if isinstance(proposed, ProposedMultipleChoiceQuestion)
            else _validate_text_question(
                proposed=proposed, passages=passages, counts=counts
            )
        )
        if validated is not None:
            questions.append(validated)
    return tuple(questions), counts


def _validate_sentence(
    proposed: ProposedSummarySentence,
    passages: Sequence[RetrievedPassage],
    counts: Counter[str],
) -> SummarySentence | None:
    citations = _resolve_citations(
        proposed=proposed.citations, passages=passages, counts=counts
    )
    return (
        None
        if citations is None
        else SummarySentence(text=proposed.text, citations=citations)
    )


def _validate_section(
    proposed: ProposedSummarySection,
    passages: Sequence[RetrievedPassage],
    counts: Counter[str],
) -> SummarySection | None:
    sentences = tuple(
        sentence
        for sentence in (
            _validate_sentence(proposed=item, passages=passages, counts=counts)
            for item in proposed.sentences
        )
        if sentence is not None
    )
    return (
        SummarySection(title=proposed.title, sentences=sentences) if sentences else None
    )


def validate_summary_response(
    response: SummaryResponse, passages: Sequence[RetrievedPassage]
) -> tuple[tuple[SummarySection, ...], Counter[str]]:
    counts: Counter[str] = Counter()
    sections = tuple(
        section
        for section in (
            _validate_section(proposed=item, passages=passages, counts=counts)
            for item in response.sections
        )
        if section is not None
    )
    return sections, counts


def discard_counts(counts: Counter[str]) -> tuple[DiscardCount, ...]:
    return tuple(
        DiscardCount(reason=reason, count=count)
        for reason, count in sorted(counts.items())
    )
