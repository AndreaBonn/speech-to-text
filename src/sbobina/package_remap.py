"""Remap loaded domain records without storage access or input mutation."""

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import assert_never
from uuid import uuid4

from sbobina.card_models import (
    Anchor,
    CardCreated,
    CardEvent,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
)
from sbobina.course_registry import CourseRecord
from sbobina.courses import MAX_COURSE_LABEL_LENGTH, course_key, normalize_course_label
from sbobina.generation_models import (
    GenerationCitation,
    GenerationQuestion,
    GenerationRecord,
    GenerationSources,
    GenerationSourceUsed,
    SummarySection,
)
from sbobina.package_remap_types import (
    IdMaps,
    ImportedFrom,
    PackageContent,
    PackageJob,
    RemappedPackage,
    RemapRequest,
)

__all__ = [
    "IdMaps",
    "ImportedFrom",
    "PackageContent",
    "PackageJob",
    "PackageRemapError",
    "RemapRequest",
    "RemappedPackage",
    "remap_package",
]

FIRST_COLLISION_INDEX = 2

# Bidi embeddings, overrides and isolates (U+202A-U+202E, U+2066-U+2069).
BIDI_CONTROLS = frozenset(
    "\N{LEFT-TO-RIGHT EMBEDDING}\N{RIGHT-TO-LEFT EMBEDDING}"
    "\N{POP DIRECTIONAL FORMATTING}\N{LEFT-TO-RIGHT OVERRIDE}"
    "\N{RIGHT-TO-LEFT OVERRIDE}\N{LEFT-TO-RIGHT ISOLATE}"
    "\N{RIGHT-TO-LEFT ISOLATE}\N{FIRST STRONG ISOLATE}"
    "\N{POP DIRECTIONAL ISOLATE}"
)


class PackageRemapError(ValueError):
    code = "PACKAGE_REMAP_INVALID"


def _new_ids(values: Iterable[str]) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if not value or value in result:
            raise PackageRemapError("Missing or duplicate entity ID")
        result[value] = str(uuid4())
    return MappingProxyType(result)


def _source_course(content: PackageContent) -> str | None:
    course_ids = {document.course_id for document in content.documents}
    if content.course_id is not None:
        course_ids.add(content.course_id)
    if len(course_ids) > 1:
        raise PackageRemapError("Package contains multiple source courses")
    return next(iter(course_ids), None)


def _tables(content: PackageContent, source_course: str | None) -> IdMaps:
    return IdMaps(
        courses=_new_ids(values=() if source_course is None else (source_course,)),
        jobs=_new_ids(values=(job.id for job in content.jobs)),
        documents=_new_ids(values=(doc.id for doc in content.documents)),
        generations=_new_ids(values=(gen.id for gen in content.generations)),
        cards=_new_ids(
            values=(
                event.card_id
                for event in content.cards
                if isinstance(event, CardCreated)
            )
        ),
    )


def _lookup(table: Mapping[str, str], value: str) -> str:
    if value not in table:
        raise PackageRemapError(f"Dangling entity reference: {value}")
    return table[value]


def _reference(table: Mapping[str, str], value: str | None) -> str | None:
    return None if value is None else _lookup(table=table, value=value)


def _citation(citation: GenerationCitation, ids: IdMaps) -> GenerationCitation:
    doc_id = _reference(table=ids.documents, value=citation.doc_id)
    job_id = _reference(table=ids.jobs, value=citation.job_id)
    if citation.doc_id is not None:
        old_prefix, new_prefix = f"{citation.doc_id}:p", f"{doc_id}:p"
    else:
        old_prefix, new_prefix = f"L{citation.job_id}-S", f"L{job_id}-S"
    if not citation.passage_id.startswith(old_prefix):
        raise PackageRemapError("Citation passage ID does not match its source")
    passage_id = new_prefix + citation.passage_id[len(old_prefix) :]
    return replace(citation, doc_id=doc_id, job_id=job_id, passage_id=passage_id)


def _source(source: GenerationSourceUsed, ids: IdMaps) -> GenerationSourceUsed:
    return replace(
        source,
        doc_id=_reference(table=ids.documents, value=source.doc_id),
        job_id=_reference(table=ids.jobs, value=source.job_id),
    )


def _section(section: SummarySection, ids: IdMaps) -> SummarySection:
    return replace(
        section,
        sentences=tuple(
            replace(
                sentence,
                citations=tuple(
                    _citation(citation=item, ids=ids) for item in sentence.citations
                ),
            )
            for sentence in section.sentences
        ),
    )


def _requested_sources(sources: GenerationSources, ids: IdMaps) -> GenerationSources:
    return GenerationSources(
        doc_ids=tuple(
            _lookup(table=ids.documents, value=value) for value in sources.doc_ids
        ),
        job_ids=tuple(
            _lookup(table=ids.jobs, value=value) for value in sources.job_ids
        ),
    )


def _question(question: GenerationQuestion, ids: IdMaps) -> GenerationQuestion:
    return replace(
        question,
        citations=tuple(
            _citation(citation=item, ids=ids) for item in question.citations
        ),
    )


def _generation(record: GenerationRecord, ids: IdMaps) -> GenerationRecord:
    return replace(
        record,
        id=_lookup(table=ids.generations, value=record.id),
        sources=tuple(_source(source=source, ids=ids) for source in record.sources),
        requested_sources=_requested_sources(sources=record.requested_sources, ids=ids),
        questions=tuple(
            _question(question=question, ids=ids) for question in record.questions
        ),
        sections=tuple(
            _section(section=section, ids=ids) for section in record.sections
        ),
    )


def _anchor(anchor: Anchor, ids: IdMaps) -> Anchor:
    match anchor:
        case LectureAnchor():
            return replace(anchor, job_id=_lookup(table=ids.jobs, value=anchor.job_id))
        case DocumentAnchor():
            return replace(
                anchor, doc_id=_lookup(table=ids.documents, value=anchor.doc_id)
            )
        case GenerationAnchor():
            return replace(
                anchor,
                generation_id=_lookup(
                    table=ids.generations, value=anchor.generation_id
                ),
            )
        case _ as unhandled:
            assert_never(unhandled)


def _card(event: CardEvent, ids: IdMaps) -> CardEvent:
    card_id = _lookup(table=ids.cards, value=event.card_id)
    if isinstance(event, CardCreated):
        return replace(
            event, card_id=card_id, anchor=_anchor(anchor=event.anchor, ids=ids)
        )
    return replace(event, card_id=card_id)


def _clean_label(raw: str) -> str:
    """The package label as any other course label, without hidden characters.

    A shared package is untrusted: bidi overrides can make one course name
    read as another, and the 100-character limit of the registry applies.
    """
    visible = "".join(
        " " if char.isspace() else char
        for char in raw
        if char.isspace()
        or (char not in BIDI_CONTROLS and unicodedata.category(char) != "Cc")
    )
    try:
        label = normalize_course_label(raw=visible)
    except ValueError as error:
        raise PackageRemapError(
            f"Course label longer than {MAX_COURSE_LABEL_LENGTH} characters"
        ) from error
    if label is None:
        raise PackageRemapError("Course label is empty once cleaned")
    return label


def _suffixed(label: str, date: str, index: int | None) -> str:
    # The label is cut, never the suffix, so the result stays a valid label.
    suffix = f" (importato {date})" + (f" ({index})" if index else "")
    return label[: MAX_COURSE_LABEL_LENGTH - len(suffix)].rstrip() + suffix


def _label(request: RemapRequest) -> str:
    label = _clean_label(raw=request.manifest.course.label)
    existing = request.existing_course_keys
    if course_key(label=label) not in existing:
        return label
    date = request.manifest.created_at.date().isoformat()
    candidate, index = _suffixed(label=label, date=date, index=None), None
    while course_key(label=candidate) in existing:
        index = FIRST_COLLISION_INDEX if index is None else index + 1
        candidate = _suffixed(label=label, date=date, index=index)
    return candidate


def _content(content: PackageContent, ids: IdMaps, course_id: str) -> PackageContent:
    return PackageContent(
        course_id=course_id,
        jobs=tuple(
            replace(job, id=_lookup(table=ids.jobs, value=job.id))
            for job in content.jobs
        ),
        documents=tuple(
            replace(
                doc, id=_lookup(table=ids.documents, value=doc.id), course_id=course_id
            )
            for doc in content.documents
        ),
        generations=tuple(
            _generation(record=record, ids=ids) for record in content.generations
        ),
        cards=tuple(_card(event=event, ids=ids) for event in content.cards),
    )


def _course(request: RemapRequest, course_id: str) -> CourseRecord:
    label = _label(request=request)
    return CourseRecord(
        id=course_id,
        key=course_key(label=label),
        label=label,
        created_at=request.manifest.created_at,
        updated_at=request.manifest.created_at,
    )


def remap_package(request: RemapRequest) -> RemappedPackage:
    """Allocate UUID4 identities and rewrite typed references, without I/O.

    Parameters
    ----------
    request : RemapRequest
        Domain records loaded by the caller, manifest and registered course keys.
        Source course identity is optional because v1 manifests omit it; document
        metadata can supply it. Provenance intentionally retains original IDs.
        Free prose and payloads retain their content; only identity fields change.
    """
    source_course = _source_course(content=request.content)
    ids = _tables(content=request.content, source_course=source_course)
    course_id = (
        ids.courses[source_course] if source_course is not None else str(uuid4())
    )
    return RemappedPackage(
        course=_course(request=request, course_id=course_id),
        content=_content(content=request.content, ids=ids, course_id=course_id),
        imported_from=ImportedFrom(
            package_id=str(request.manifest.package_id), ids=ids
        ),
    )
