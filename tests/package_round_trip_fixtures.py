import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from package_fixtures import NOW, seed_document
from study_fixtures import QUOTE, transcript_fixture

from sbobina.card_models import (
    Anchor,
    CardDraft,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
)
from sbobina.course_registry import CourseRecord, get_or_create
from sbobina.document_models import CourseDocument
from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationRequest,
    GenerationSources,
    GenerationSourceUsed,
    GenerationStatus,
    SummarySection,
    SummarySentence,
)
from sbobina.models import transcript_to_json
from sbobina.web.card_store import create_card
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.document_store import document_dir, read_document
from sbobina.web.generation_store import create_generation, save_generation
from sbobina.web.job_models import JobConfig, JobStatus
from sbobina.web.job_store import JobStore

LABEL = "Fisica"
LECTURE_COUNT = 2
CARD_COUNT = 10
DOCUMENT_QUOTE = "Course notes"
OPTIONS = ("Prima", "Seconda", "Terza", "Quarta")


@dataclass(frozen=True)
class SourceCourse:
    data_dir: Path
    store: JobStore
    course: CourseRecord
    job_ids: tuple[str, ...]
    doc_id: str


def seed_round_trip_course(data_dir: Path) -> SourceCourse:
    """2 lectures, 1 document with text, 1 generation per format, 10 cards (C5)."""
    store = JobStore(data_dir=data_dir)
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label=LABEL)
    transcript = transcript_to_json(transcript=transcript_fixture())
    job_ids = []
    for _ in range(LECTURE_COUNT):
        job = store.create(config=JobConfig(subject=LABEL), source_name="Lezione.m4a")
        store.update(record=job.model_copy(update={"status": JobStatus.DONE}))
        directory = store.jobs_dir / str(job.id)
        (directory / "audio.json").write_text(data=transcript, encoding="utf-8")
        (directory / "audio.corretto.json").write_text(
            data=transcript, encoding="utf-8"
        )
        job_ids.append(str(job.id))
    source = SourceCourse(
        data_dir=data_dir,
        store=store,
        course=course,
        job_ids=tuple(job_ids),
        doc_id=seed_document(store=store, course=course),
    )
    generation_ids = [
        seed_generation(source=source, generation_format=generation_format)
        for generation_format in GenerationFormat
    ]
    seed_cards(source=source, generation_ids=generation_ids)
    return source


def citations(source: SourceCourse) -> tuple[GenerationCitation, ...]:
    lecture = tuple(
        GenerationCitation(
            passage_id=f"L{job_id}-S1",
            quote=QUOTE,
            doc_id=None,
            page=None,
            job_id=job_id,
            timestamp=10.0,
        )
        for job_id in source.job_ids
    )
    document = GenerationCitation(
        passage_id=f"{source.doc_id}:p1:c0",
        quote=DOCUMENT_QUOTE,
        doc_id=source.doc_id,
        page=1,
        job_id=None,
        timestamp=None,
    )
    return (*lecture, document)


def sources_used(source: SourceCourse) -> tuple[GenerationSourceUsed, ...]:
    document = read_document(
        courses_dir=source.store.courses_dir,
        course_id=source.course.id,
        doc_id=source.doc_id,
    )
    lectures = tuple(
        GenerationSourceUsed(
            doc_id=None,
            sha256=None,
            job_id=job_id,
            revision=lecture_revision(store=source.store, job_id=job_id),
        )
        for job_id in source.job_ids
    )
    return (
        GenerationSourceUsed(
            doc_id=source.doc_id, sha256=document.sha256, job_id=None, revision=None
        ),
        *lectures,
    )


def cited_content(
    generation_format: GenerationFormat, cited: tuple[GenerationCitation, ...]
) -> dict[str, Any]:
    """Questions, or sections for a summary, all citing every source."""
    if generation_format is GenerationFormat.SUMMARY:
        sentence = SummarySentence(text="Frase", citations=cited)
        return {
            "questions": (),
            "sections": (SummarySection(title="Sintesi", sentences=(sentence,)),),
        }
    is_mc = generation_format is GenerationFormat.MULTIPLE_CHOICE
    question = GenerationQuestion(
        question=f"Domanda {generation_format}",
        options=OPTIONS if is_mc else (),
        correct_index=0 if is_mc else None,
        solution="Soluzione",
        citations=cited,
    )
    return {"questions": (question,), "sections": ()}


def seed_generation(source: SourceCourse, generation_format: GenerationFormat) -> str:
    queued = create_generation(
        courses_dir=source.store.courses_dir,
        course_id=source.course.id,
        request=GenerationRequest(
            format=generation_format,
            count=1,
            sources=GenerationSources(doc_ids=(source.doc_id,), job_ids=source.job_ids),
        ),
    )
    done = replace(
        queued,
        status=GenerationStatus.DONE,
        model="test",
        prompt_version="test",
        generated_at=NOW.isoformat(),
        sources=sources_used(source=source),
        **cited_content(
            generation_format=generation_format, cited=citations(source=source)
        ),
    )
    save_generation(
        courses_dir=source.store.courses_dir, course_id=source.course.id, record=done
    )
    return done.id


def card_anchors(source: SourceCourse, generation_ids: list[str]) -> list[Anchor]:
    document = read_document(
        courses_dir=source.store.courses_dir,
        course_id=source.course.id,
        doc_id=source.doc_id,
    )
    anchors: list[Anchor] = [
        GenerationAnchor(generation_id=generation_id, question_index=0)
        for generation_id in generation_ids
    ]
    for job_id in source.job_ids:
        revision = lecture_revision(store=source.store, job_id=job_id)
        assert revision is not None
        anchors += [
            LectureAnchor(
                job_id=job_id, revision=revision, segment_index=1, quote=QUOTE
            ),
            DocumentAnchor(
                doc_id=document.id,
                sha256=document.sha256,
                page=1,
                quote=DOCUMENT_QUOTE,
            ),
        ]
    while len(anchors) < CARD_COUNT:
        anchors.append(anchors[len(generation_ids)])
    return anchors


def seed_cards(source: SourceCourse, generation_ids: list[str]) -> None:
    for index, anchor in enumerate(
        card_anchors(source=source, generation_ids=generation_ids)
    ):
        create_card(
            courses_dir=source.store.courses_dir,
            course_id=source.course.id,
            now=NOW,
            draft=CardDraft(
                front=f"Fronte {index}", back="Retro", source=LABEL, anchor=anchor
            ),
        )


def document_text(courses_dir: Path, document: CourseDocument) -> list[str]:
    """Text of each page; import rewrites text.json with loader defaults."""
    directory = document_dir(
        courses_dir=courses_dir, course_id=document.course_id, doc_id=document.id
    )
    content = json.loads((directory / "text.json").read_bytes())
    return [page["text"] for page in content["pages"]]
