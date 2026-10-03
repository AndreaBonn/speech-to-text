"""Citation resolution for the generations API detail view (T034).

Mirrors api_study.py's CitationContext: a document citation resolves to its
current filename and a reader link, or "fonte rimossa" if the document was
deleted since the generation ran. A lecture citation resolves to the exact
timestamp by re-locating the quote in the lecture's current transcript
(study_citations.locate_quote) near the window anchor recorded at generation
time, falling back to that anchor if the transcript changed enough that the
quote no longer matches.
"""

from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from sbobina.generation_models import (
    GenerationCitation,
    GenerationQuestion,
    GenerationRecord,
    SummarySection,
    SummarySentence,
)
from sbobina.lecture_windows import WINDOW_WORDS
from sbobina.models import Transcript, load_transcript
from sbobina.study_citations import locate_quote
from sbobina.study_models import Rejection
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.document_store import document_dir, read_document, read_text
from sbobina.web.errors import NotFoundError
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import PREFERRED_VARIANTS

REMOVED_SOURCE = "fonte rimossa"
LECTURE_SOURCE = "lezione"


@dataclass(frozen=True)
class CitationContext:
    courses_dir: Path
    store: JobStore
    course_id: str
    key: str


def _document_citation(
    citation: GenerationCitation, context: CitationContext
) -> dict[str, Any]:
    assert citation.doc_id is not None and citation.page is not None
    try:
        document = read_document(
            courses_dir=context.courses_dir,
            course_id=context.course_id,
            doc_id=citation.doc_id,
        )
    except NotFoundError:
        return {"quote": citation.quote, "source": REMOVED_SOURCE, "href": None}
    href = f"/corsi/{context.key}/documenti/{citation.doc_id}?p={citation.page}"
    return {
        "quote": citation.quote,
        "source": document.filename,
        "page": citation.page,
        "href": href,
        "ocr": _page_is_ocr(
            context=context, doc_id=citation.doc_id, page=citation.page
        ),
    }


def _page_is_ocr(context: CitationContext, doc_id: str, page: int) -> bool:
    """Whether the cited page was read by OCR, which can change wording (T050)."""
    doc_dir = document_dir(
        courses_dir=context.courses_dir, course_id=context.course_id, doc_id=doc_id
    )
    try:
        pages = read_text(doc_dir=doc_dir).pages
    except (OSError, ValueError, KeyError):
        return False
    return 1 <= page <= len(pages) and pages[page - 1].ocr


def _lecture_transcript(store: JobStore, job_id: str) -> tuple[Transcript, str] | None:
    """The lecture's current best transcript, and which variant it came from."""
    directory = store.jobs_dir / job_id
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        if not path.is_file():
            continue
        try:
            return load_transcript(path=path), variant
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return None


def _anchor_index(transcript: Transcript, timestamp: float) -> int | None:
    return next(
        (
            index
            for index, segment in enumerate(transcript.segments)
            if segment.start == timestamp
        ),
        None,
    )


def _window_starts(transcript: Transcript, anchor: int) -> list[int]:
    """Segments a passage window around anchor may cover, nearest first.

    Course sampling starts the window at the anchor, topic search centres it
    on the anchor, and locate_quote only looks at a segment and the next one:
    so every segment within WINDOW_WORDS of the anchor, on both sides, is a
    candidate start.
    """
    segments = transcript.segments

    def reach(step: int) -> list[int]:
        found, words, index = [], 0, anchor + step
        while 0 <= index < len(segments) and words < WINDOW_WORDS:
            found.append(index)
            words += len(segments[index].words)
            index += step
        return found

    after, before = reach(step=1), reach(step=-1)
    interleaved = [
        i for pair in zip_longest(after, before) for i in pair if i is not None
    ]
    return [anchor, *interleaved]


def _exact_timestamp(
    citation: GenerationCitation, loaded: tuple[Transcript, str] | None
) -> float:
    assert citation.timestamp is not None
    if loaded is None:
        return citation.timestamp
    transcript, _variant = loaded
    index = _anchor_index(transcript=transcript, timestamp=citation.timestamp)
    if index is None:
        return citation.timestamp
    allowed = frozenset(range(len(transcript.segments)))
    for start in _window_starts(transcript=transcript, anchor=index):
        match = locate_quote(
            segments=transcript.segments,
            segment_index=start,
            quote=citation.quote,
            allowed=allowed,
        )
        if not isinstance(match, Rejection):
            return match.timestamp
    return citation.timestamp


def _lecture_citation(
    citation: GenerationCitation, context: CitationContext
) -> dict[str, Any]:
    assert citation.job_id is not None
    if not (context.store.jobs_dir / citation.job_id).is_dir():
        return {"quote": citation.quote, "source": REMOVED_SOURCE, "href": None}
    loaded = _lecture_transcript(store=context.store, job_id=citation.job_id)
    timestamp = _exact_timestamp(citation=citation, loaded=loaded)
    variant = loaded[1] if loaded is not None else "original"
    href = f"/lettore/{citation.job_id}?t={timestamp}&variant={variant}"
    return {
        "quote": citation.quote,
        "source": LECTURE_SOURCE,
        "timestamp": timestamp,
        "href": href,
    }


def resolve_citation(
    citation: GenerationCitation, context: CitationContext
) -> dict[str, Any]:
    if citation.doc_id is not None:
        return _document_citation(citation=citation, context=context)
    return _lecture_citation(citation=citation, context=context)


def _question_payload(
    question: GenerationQuestion, context: CitationContext
) -> dict[str, Any]:
    payload: dict[str, Any] = jsonable_encoder(obj=question)
    payload["citations"] = [
        resolve_citation(citation=citation, context=context)
        for citation in question.citations
    ]
    return payload


def _sentence_payload(
    sentence: SummarySentence, context: CitationContext
) -> dict[str, Any]:
    payload: dict[str, Any] = jsonable_encoder(obj=sentence)
    payload["citations"] = [
        resolve_citation(citation=citation, context=context)
        for citation in sentence.citations
    ]
    return payload


def _section_payload(
    section: SummarySection, context: CitationContext
) -> dict[str, Any]:
    return {
        "title": section.title,
        "sentences": [
            _sentence_payload(sentence=sentence, context=context)
            for sentence in section.sentences
        ],
    }


def generation_detail_payload(
    record: GenerationRecord, context: CitationContext
) -> dict[str, Any]:
    payload: dict[str, Any] = jsonable_encoder(obj=record)
    payload["questions"] = [
        _question_payload(question=question, context=context)
        for question in record.questions
    ]
    payload["sections"] = [
        _section_payload(section=section, context=context)
        for section in record.sections
    ]
    return payload


def doc_filenames(
    courses_dir: Path, course_id: str, record: GenerationRecord
) -> dict[str, str]:
    """doc_id -> current filename, for citations rendered into exports."""
    names: dict[str, str] = {}
    for source in record.sources:
        if source.doc_id is None:
            continue
        try:
            document = read_document(
                courses_dir=courses_dir, course_id=course_id, doc_id=source.doc_id
            )
        except NotFoundError:
            continue
        names[source.doc_id] = document.filename
    return names
