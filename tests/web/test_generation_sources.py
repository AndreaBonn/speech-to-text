"""A3: a generation must register the sources it used (ADR D5)."""

from datetime import UTC, datetime
from pathlib import Path

from study_fixtures import FakeChat

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.generation_models import GenerationFormat, GenerationRequest
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.retrieval import DocumentSource, LectureSource, RetrievedPassage
from sbobina.web.api_files import TRANSCRIPT_FILES, transcript_revision
from sbobina.web.document_store import document_dir, write_document, write_text
from sbobina.web.generation_runner import (
    GenerationJob,
    build_sources,
    execute_generation,
)
from sbobina.web.generation_store import create_generation, load_generation
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

VALID_REPLY = (
    '{"domande": [{"domanda": "Che colore ha il gatto?", '
    '"opzioni": ["nero", "bianco", "rosso", "verde"], "corretta": 0, '
    '"soluzione": "nero", "citazioni": [{"passaggio": "P1", '
    '"testo": "gatto nero dorme sul tappeto"}]}]}'
)


def _doc_passage(doc_id: str) -> RetrievedPassage:
    return RetrievedPassage(
        text="testo",
        source=DocumentSource(doc_id=doc_id, page=1, chunk=0),
        passage_id=f"{doc_id}:p1:c0",
    )


def _lecture_passage(job_id: str) -> RetrievedPassage:
    return RetrievedPassage(
        text="testo",
        source=LectureSource(job_id=job_id, segment_index=0, start=0.0),
        passage_id=f"L{job_id}-S0",
    )


def test_build_sources_collects_one_entry_per_distinct_doc_and_lecture() -> None:
    passages = [
        _doc_passage("doc-1"),
        _doc_passage("doc-1"),
        _doc_passage("doc-2"),
        _lecture_passage("job-1"),
    ]

    sources = build_sources(
        passages=passages,
        doc_sha256=lambda doc_id: f"sha-{doc_id}",
        find_lecture_revision=lambda job_id: f"rev-{job_id}",
    )

    assert {s.doc_id for s in sources if s.doc_id is not None} == {"doc-1", "doc-2"}
    assert [s.sha256 for s in sources if s.doc_id == "doc-1"] == ["sha-doc-1"]
    assert [s.revision for s in sources if s.job_id == "job-1"] == ["rev-job-1"]
    assert len(sources) == 3


def test_build_sources_drops_a_source_whose_lookup_finds_nothing() -> None:
    sources = build_sources(
        passages=[_doc_passage("doc-gone")],
        doc_sha256=lambda _doc_id: None,
        find_lecture_revision=lambda _job_id: None,
    )

    assert sources == ()


def _write_lecture(store: JobStore, job_id: str) -> str:
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=1.0,
        segments=(
            Segment(
                start=0.0,
                end=1.0,
                words=(
                    Word(
                        start=0.0,
                        end=1.0,
                        text="il gatto nero dorme sul tappeto",
                        probability=0.99,
                    ),
                ),
            ),
        ),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TRANSCRIPT_FILES["original"]
    save_transcript(transcript=transcript, path=path)
    return transcript_revision(path.read_text(encoding="utf-8"))


def _job(
    store: JobStore, course_id: str, course_key: str, request: GenerationRequest
) -> GenerationJob:
    record = create_generation(
        courses_dir=store.courses_dir, course_id=course_id, request=request
    )
    return GenerationJob(
        store=store,
        index_path=store.jobs_dir.parent / "search.sqlite3",
        course_id=course_id,
        course_key=course_key,
        record=record,
    )


def test_execute_generation_records_the_lecture_revision_it_retrieved(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    expected_revision = _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)

    execute_generation(job=job, chat=lambda _request: VALID_REPLY, model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert len(saved.sources) == 1
    assert saved.sources[0].job_id == str(lecture.id)
    assert saved.sources[0].revision == expected_revision


def _write_document(
    tmp_path: Path, store: JobStore, course_id: str, doc_id: str
) -> str:
    courses_dir = store.courses_dir
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    doc_dir.mkdir(parents=True)
    sha256 = "b" * 64
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course_id,
            filename="Manuale.pdf",
            kind=DocumentKind.PDF,
            size=10,
            sha256=sha256,
            status=DocumentStatus.READY,
            error=None,
            pages=1,
            created_at=datetime.now(UTC),
        ),
    )
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=(
                Page(
                    text="la forza e massa per accelerazione del corpo rigido",
                    no_text=False,
                    ocr=False,
                ),
            ),
            status=DocumentStatus.READY,
        ),
    )
    return sha256


def test_execute_generation_records_the_document_sha256_it_retrieved(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    expected_sha256 = _write_document(
        tmp_path=tmp_path, store=store, course_id=course.id, doc_id="doc-1"
    )
    request = GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=1)
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)
    fake_chat = FakeChat(responses=[VALID_REPLY])

    execute_generation(job=job, chat=fake_chat, model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert len(saved.sources) == 1
    assert saved.sources[0].doc_id == "doc-1"
    assert saved.sources[0].sha256 == expected_sha256
