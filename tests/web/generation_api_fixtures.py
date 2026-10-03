"""Shared app client and record builders for the generations API tests."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.generation_models import (
    GenerationFormat,
    GenerationQuestion,
    GenerationRecord,
    GenerationRequest,
    GenerationSourceUsed,
    GenerationStatus,
    SummarySection,
)
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.settings import Settings
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.app import create_app
from sbobina.web.document_store import document_dir, write_document
from sbobina.web.generation_store import (
    create_generation,
    save_generation,
)
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
COURSES_URL = "/api/v1/courses"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def _store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


def _register_course(tmp_path: Path, key: str = "fisica") -> str:
    course = get_or_create(
        courses_dir=_store(tmp_path).courses_dir, key=key, label=key.title()
    )
    return course.id


def _write_document(tmp_path: Path, course_id: str, doc_id: str, filename: str) -> None:
    courses_dir = _store(tmp_path).courses_dir
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    doc_dir.mkdir(parents=True)
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course_id,
            filename=filename,
            kind=DocumentKind.PDF,
            size=10,
            sha256="a" * 64,
            status=DocumentStatus.READY,
            error=None,
            pages=1,
            created_at=datetime.now(UTC),
        ),
    )


def _write_lecture(tmp_path: Path, job_id: str) -> None:
    store = _store(tmp_path)
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=10.0,
        segments=(
            Segment(
                start=0.0,
                end=6.0,
                words=(
                    Word(start=0.0, end=1.0, text="il ", probability=0.99),
                    Word(start=1.0, end=2.0, text="gatto ", probability=0.99),
                    Word(start=2.0, end=3.0, text="nero ", probability=0.99),
                    Word(start=3.0, end=4.0, text="dorme ", probability=0.99),
                    Word(start=4.0, end=5.0, text="sul ", probability=0.99),
                    Word(start=5.0, end=6.0, text="tappeto", probability=0.99),
                ),
            ),
        ),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )


def _make_record(
    tmp_path: Path,
    course_id: str,
    *,
    format_: GenerationFormat = GenerationFormat.MULTIPLE_CHOICE,
    status: GenerationStatus = GenerationStatus.QUEUED,
    questions: tuple[GenerationQuestion, ...] = (),
    sections: tuple[SummarySection, ...] = (),
    sources: tuple[GenerationSourceUsed, ...] = (),
) -> GenerationRecord:
    courses_dir = _store(tmp_path).courses_dir
    base = create_generation(
        courses_dir=courses_dir,
        course_id=course_id,
        request=GenerationRequest(format=format_, count=1),
    )
    is_done = status == GenerationStatus.DONE
    record = replace(
        base,
        status=status,
        questions=questions,
        sections=sections,
        sources=sources,
        model="qwen-test" if is_done else "",
        prompt_version="v1" if is_done else "",
        generated_at="2026-01-01T00:00:00" if is_done else "",
    )
    save_generation(courses_dir=courses_dir, course_id=course_id, record=record)
    return record


def _mc_question(correct: str) -> GenerationQuestion:
    return GenerationQuestion(
        question="Quale e' corretta?",
        options=("a", "b", "c", "d"),
        correct_index=0,
        solution=correct,
        citations=(),
    )


def _write_long_lecture(tmp_path: Path, job_id: str) -> None:
    """Six segments, 10 s apart: segment n holds "parolaN1 parolaN2 parolaN3"."""
    segments = tuple(
        Segment(
            start=10.0 * n,
            end=10.0 * n + 3.0,
            words=tuple(
                Word(
                    start=10.0 * n + k,
                    end=10.0 * n + k + 1.0,
                    text=f"parola{n}{k} ",
                    probability=0.99,
                )
                for k in range(3)
            ),
        )
        for n in range(6)
    )
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=60.0,
        segments=segments,
    )
    directory = _store(tmp_path).jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )
