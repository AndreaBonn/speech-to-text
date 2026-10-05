from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from package_fixtures import seed_package
from pydantic import TypeAdapter

from sbobina.card_models import (
    CardCreated,
    CardDeleted,
    CardSuspended,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
    load_card_event,
)
from sbobina.document_models import CourseDocument
from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationRecord,
    GenerationSources,
    GenerationSourceUsed,
    GenerationStatus,
    SummarySection,
    SummarySentence,
    load_generation,
)
from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import ExportOptions, Manifest
from sbobina.package_remap_types import PackageContent, PackageJob, RemapRequest

IMPORT_DATE = datetime(2026, 10, 4, tzinfo=UTC)


def exported_request(tmp_path: Path) -> RemapRequest:
    fixture = seed_package(tmp_path=tmp_path, label="Diritto privato")
    stream = BytesIO()
    write_package(
        target=stream,
        request=ExportRequest(
            store=fixture.store,
            course=fixture.course,
            now=IMPORT_DATE,
            options=ExportOptions(),
        ),
    )
    with ZipFile(file=stream) as archive:
        contents = {name: archive.read(name=name) for name in archive.namelist()}
    return RemapRequest(
        manifest=Manifest.model_validate_json(json_data=contents["manifest.json"]),
        content=enrich_content(
            content=loaded_content(contents=contents, course_id=fixture.course.id)
        ),
        existing_course_keys=frozenset(),
    )


def loaded_content(contents: dict[str, bytes], course_id: str) -> PackageContent:
    return PackageContent(
        course_id=course_id,
        jobs=(TypeAdapter(PackageJob).validate_json(contents["lectures/0/meta.json"]),),
        documents=tuple(
            TypeAdapter(CourseDocument).validate_json(
                contents[f"documents/{i}/document.json"]
            )
            for i in range(2)
        ),
        generations=(load_generation(content=contents["generations/0.json"].decode()),),
        cards=tuple(
            load_card_event(content=line)
            for line in contents["cards/cards.jsonl"].decode().splitlines()
        ),
    )


def source_citations(job_id: str, doc_id: str) -> tuple[GenerationCitation, ...]:
    return (
        GenerationCitation(
            passage_id=f"{doc_id}:p12:c3",
            quote="Document quote",
            doc_id=doc_id,
            page=12,
            job_id=None,
            timestamp=None,
        ),
        GenerationCitation(
            passage_id=f"L{job_id}-S42",
            quote="Lecture quote",
            doc_id=None,
            page=None,
            job_id=job_id,
            timestamp=2.0,
        ),
    )


def question_generation(content: PackageContent) -> GenerationRecord:
    job_id, doc_id = content.jobs[0].id, content.documents[0].id
    return replace(
        content.generations[0],
        status=GenerationStatus.DONE,
        questions=(
            GenerationQuestion(
                question="Question",
                options=(),
                correct_index=None,
                solution="Answer",
                citations=source_citations(job_id=job_id, doc_id=doc_id),
            ),
        ),
        sources=(
            GenerationSourceUsed(
                doc_id=doc_id, sha256="hash", job_id=None, revision=None
            ),
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id=job_id, revision="revision"
            ),
        ),
        requested_sources=GenerationSources(doc_ids=(doc_id,), job_ids=(job_id,)),
    )


def enrich_content(content: PackageContent) -> PackageContent:
    job_id, doc_id = content.jobs[0].id, content.documents[0].id
    generation = question_generation(content=content)
    summary = replace(
        generation,
        id=str(uuid4()),
        format=GenerationFormat.SUMMARY,
        questions=(),
        sections=(
            SummarySection(
                title="Summary",
                sentences=(
                    SummarySentence(
                        text="Text", citations=generation.questions[0].citations
                    ),
                ),
            ),
        ),
    )
    return replace(
        content,
        generations=(generation, summary),
        cards=content.cards + extra_cards(job_id=job_id, doc_id=doc_id),
    )


def extra_cards(
    job_id: str, doc_id: str
) -> tuple[CardCreated | CardSuspended | CardDeleted, ...]:
    anchors = (
        LectureAnchor(
            job_id=job_id, revision="revision", segment_index=42, quote="Quote"
        ),
        DocumentAnchor(doc_id=doc_id, sha256="hash", page=12, quote="Quote"),
    )
    cards = tuple(
        CardCreated(
            card_id=str(uuid4()),
            occurred_at=IMPORT_DATE,
            front="Front",
            back="Back",
            source="Source",
            anchor=anchor,
        )
        for anchor in anchors
    )
    return (
        *cards,
        CardSuspended(card_id=cards[0].card_id, occurred_at=IMPORT_DATE),
        CardDeleted(card_id=cards[1].card_id, occurred_at=IMPORT_DATE),
    )


def shared_namespace_content(content: PackageContent) -> PackageContent:
    shared = str(uuid4())
    generation = replace(
        content.generations[0],
        id=shared,
        status=GenerationStatus.QUEUED,
        sources=(),
        requested_sources=GenerationSources(),
        questions=(),
    )
    created = next(event for event in content.cards if isinstance(event, CardCreated))
    return PackageContent(
        course_id=shared,
        jobs=(replace(content.jobs[0], id=shared),),
        documents=(replace(content.documents[0], id=shared, course_id=shared),),
        generations=(generation,),
        cards=(
            replace(
                created,
                card_id=shared,
                anchor=GenerationAnchor(generation_id=shared, question_index=0),
            ),
        ),
    )
