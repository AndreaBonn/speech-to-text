from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sbobina.card_models import CardDraft, CardEdited, GenerationAnchor
from sbobina.course_registry import CourseRecord, get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.generation_models import GenerationFormat, GenerationRequest
from sbobina.web.card_store import (
    ReviewRequest,
    append_card_event,
    create_card,
    record_review,
)
from sbobina.web.document_store import document_dir, write_document
from sbobina.web.generation_store import create_generation
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore

NOW = datetime(2026, 10, 5, tzinfo=UTC)
ORIGINAL = b"Course notes"
TEXT = b'{"pages": [{"text": "Course notes", "no_text": false}], "status": "ready", "encoding": "utf-8"}'
TRANSCRIPT = b'{"source": "lecture.m4a", "segments": []}'


@dataclass(frozen=True)
class PackageFixture:
    store: JobStore
    course: CourseRecord
    job_id: str
    document_ids: tuple[str, ...]


def seed_document(store: JobStore, course: CourseRecord) -> str:
    document = CourseDocument(
        id=str(uuid4()),
        course_id=course.id,
        filename="Notes.txt",
        kind=DocumentKind.TXT,
        size=len(ORIGINAL),
        sha256=sha256(ORIGINAL).hexdigest(),
        status=DocumentStatus.READY,
        error=None,
        pages=1,
        created_at=NOW,
    )
    write_document(courses_dir=store.courses_dir, document=document)
    directory = document_dir(
        courses_dir=store.courses_dir, course_id=course.id, doc_id=document.id
    )
    (directory / "text.json").write_bytes(TEXT)
    (directory / "original.txt").write_bytes(ORIGINAL)
    return document.id


def seed_generation_cards(store: JobStore, course: CourseRecord) -> None:
    generation = create_generation(
        courses_dir=store.courses_dir,
        course_id=course.id,
        request=GenerationRequest(format=GenerationFormat.OPEN, count=1),
    )
    card = create_card(
        courses_dir=store.courses_dir,
        course_id=course.id,
        now=NOW,
        draft=CardDraft(
            front="Question",
            back="Answer",
            source="Course",
            anchor=GenerationAnchor(generation_id=generation.id, question_index=0),
            dedup_key="preserve-this-key",
        ),
    )
    append_card_event(
        courses_dir=store.courses_dir,
        course_id=course.id,
        event=CardEdited(
            card_id=card.id, occurred_at=NOW, front="Edited", back="Answer"
        ),
    )
    seed_review(store=store, course=course, card_id=card.id)


def seed_review(store: JobStore, course: CourseRecord, card_id: str) -> None:
    record_review(
        courses_dir=store.courses_dir,
        course_id=course.id,
        request=ReviewRequest(
            card_id=card_id, rating=Rating.GOOD, observed_due=None, now=NOW
        ),
        scheduler=Scheduler(enable_fuzzing=False),
    )


def seed_private_files(directory: Path) -> None:
    for filename in (
        "practice/attempt.json",
        "chats/conversation.jsonl",
        "reviews.jsonl",
        "audio.mp3",
    ):
        path = directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"personal data")


def seed_package(tmp_path: Path, label: str = "Fisica") -> PackageFixture:
    store = JobStore(data_dir=tmp_path)
    course = get_or_create(
        courses_dir=store.courses_dir, key=label.casefold(), label=label
    )
    record = store.create(config=JobConfig(subject="Other"), source_name="Lecture.m4a")
    job_id = str(record.id)
    store.write_meta(job_id=job_id, meta=LectureMeta(course=label))
    directory = store.jobs_dir / job_id
    (directory / "audio.json").write_bytes(TRANSCRIPT)
    (directory / "audio.corretto.json").write_bytes(b'{"corrected": true}')
    (directory / "audio.studio.json").write_bytes(b'{"study": true}')
    document_ids = tuple(
        sorted(seed_document(store=store, course=course) for _ in range(2))
    )
    seed_generation_cards(store=store, course=course)
    seed_private_files(directory=directory)
    seed_private_files(directory=store.courses_dir / course.id)
    return PackageFixture(
        store=store, course=course, job_id=job_id, document_ids=document_ids
    )
