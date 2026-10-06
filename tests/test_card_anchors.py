from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from study_fixtures import QUOTE, transcript_fixture

from sbobina.card_anchors import AnchorResolution, resolve_anchor, resolve_lecture
from sbobina.card_models import DocumentAnchor, GenerationAnchor, LectureAnchor
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.generation_models import GenerationFormat, GenerationRequest
from sbobina.models import Transcript, save_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.document_store import document_dir, write_document
from sbobina.web.generation_store import create_generation, generation_path
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

KEY = "diritto"
COURSE_ID = "course"


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


def _lecture(store: JobStore) -> LectureAnchor:
    job_id = str(store.create(config=JobConfig()).id)
    save_transcript(
        transcript=transcript_fixture(),
        path=store.jobs_dir / job_id / TRANSCRIPT_FILES["original"],
    )
    revision = lecture_revision(store=store, job_id=job_id)
    assert revision is not None
    return LectureAnchor(job_id=job_id, revision=revision, segment_index=1, quote=QUOTE)


def _resolve(store: JobStore, anchor: LectureAnchor) -> AnchorResolution:
    return resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY)


def _snapshot(directory: Path) -> dict[Path, tuple[bytes, int]]:
    return {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in directory.rglob("*")
        if path.is_file()
    }


def _moved_transcript() -> Transcript:
    transcript = transcript_fixture()
    moved = replace(
        transcript.segments[1],
        start=90.0,
        words=tuple(
            replace(word, start=word.start + 80)
            for word in transcript.segments[1].words
        ),
    )
    return replace(transcript, segments=(transcript.segments[0],) * 3 + (moved,))


def test_resolve_lecture_same_revision_uses_segment_without_matching(
    store: JobStore,
) -> None:
    anchor = replace(_lecture(store=store), quote="short")
    before = _snapshot(directory=store.jobs_dir.parent)
    result = _resolve(store=store, anchor=anchor)
    assert result == AnchorResolution(
        href=f"/lettore/{anchor.job_id}?t=10.0&variant=original", status="ok"
    )
    assert _snapshot(directory=store.jobs_dir.parent) == before
    field_name = "status"
    with pytest.raises(FrozenInstanceError):
        setattr(result, field_name, "moved")


def test_resolve_lecture_changed_quote_relocates_and_disappears(
    store: JobStore,
) -> None:
    anchor = _lecture(store=store)
    corrected = store.jobs_dir / anchor.job_id / TRANSCRIPT_FILES["corrected"]
    save_transcript(transcript=_moved_transcript(), path=corrected)
    before = _snapshot(directory=store.jobs_dir.parent)
    result = _resolve(store=store, anchor=anchor)
    assert result == AnchorResolution(
        href=f"/lettore/{anchor.job_id}?t=90.0&variant=corrected", status="moved"
    )
    assert _snapshot(directory=store.jobs_dir.parent) == before
    transcript = transcript_fixture()
    save_transcript(
        transcript=replace(transcript, segments=transcript.segments[:1]), path=corrected
    )
    assert _resolve(store=store, anchor=anchor).status == "source_modified"


def test_resolve_lecture_invalid_index_relocates_without_io() -> None:
    anchor = LectureAnchor(
        job_id=str(uuid4()), revision="old", segment_index=999, quote=QUOTE
    )
    assert (
        resolve_lecture(
            anchor=anchor,
            transcript=transcript_fixture(),
            revision="old",
            variant="original",
        ).status
        == "moved"
    )
    missing = replace(anchor, quote="questa citazione è assente")
    assert (
        resolve_lecture(
            anchor=missing,
            transcript=transcript_fixture(),
            revision="old",
            variant="original",
        ).status
        == "source_modified"
    )


@pytest.mark.parametrize("content", ["{", "{}", '{"segments": null}', None])
def test_resolve_lecture_corrupted_source_returns_unavailable(
    store: JobStore, content: str | None
) -> None:
    anchor = _lecture(store=store)
    assert _resolve(store=store, anchor=anchor).status == "ok"
    corrected = store.jobs_dir / anchor.job_id / TRANSCRIPT_FILES["corrected"]
    if content is None:
        corrected.mkdir()
    else:
        corrected.write_text(data=content, encoding="utf-8")
    before = _snapshot(directory=store.jobs_dir.parent)
    assert _resolve(store=store, anchor=anchor).status == "unavailable"
    assert _snapshot(directory=store.jobs_dir.parent) == before


def test_resolve_lecture_deleted_job_returns_removed(store: JobStore) -> None:
    anchor = _lecture(store=store)
    assert _resolve(store=store, anchor=anchor).status == "ok"
    store.delete(job_id=anchor.job_id)
    assert _resolve(store=store, anchor=anchor).status == "source_removed"


def _document() -> CourseDocument:
    return CourseDocument(
        id=str(uuid4()),
        course_id=COURSE_ID,
        filename="appunti.txt",
        kind=DocumentKind.TXT,
        size=10,
        sha256="abc",
        status=DocumentStatus.READY,
        error=None,
        pages=2,
        created_at=datetime.now(tz=UTC),
    )


def test_resolve_document_hash_changes_and_removal(store: JobStore) -> None:
    document = _document()
    write_document(courses_dir=store.courses_dir, document=document)
    anchor = DocumentAnchor(
        doc_id=document.id, sha256=document.sha256, page=2, quote=QUOTE
    )
    before = _snapshot(directory=store.jobs_dir.parent)
    result = resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY)
    assert result == AnchorResolution(
        href=f"/corsi/diritto/documenti/{document.id}?p=2", status="ok"
    )
    assert _snapshot(directory=store.jobs_dir.parent) == before
    write_document(
        courses_dir=store.courses_dir, document=replace(document, sha256="def")
    )
    assert (
        resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY).status
        == "source_modified"
    )
    (
        document_dir(
            courses_dir=store.courses_dir, course_id=COURSE_ID, doc_id=document.id
        )
        / "document.json"
    ).unlink()
    assert (
        resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY).status
        == "source_removed"
    )


def test_resolve_generation_existence_and_removal(store: JobStore) -> None:
    generation = create_generation(
        courses_dir=store.courses_dir,
        course_id=COURSE_ID,
        request=GenerationRequest(format=GenerationFormat.OPEN, count=1),
    )
    anchor = GenerationAnchor(generation_id=generation.id, question_index=0)
    before = _snapshot(directory=store.jobs_dir.parent)
    result = resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY)
    assert result == AnchorResolution(
        href=f"/corsi/{KEY}/generazioni/{generation.id}", status="ok"
    )
    assert _snapshot(directory=store.jobs_dir.parent) == before
    generation_path(
        courses_dir=store.courses_dir, course_id=COURSE_ID, gen_id=generation.id
    ).unlink()
    assert (
        resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY).status
        == "source_removed"
    )


def test_resolve_document_corrupted_record_returns_unavailable(
    store: JobStore,
) -> None:
    document = _document()
    write_document(courses_dir=store.courses_dir, document=document)
    anchor = DocumentAnchor(
        doc_id=document.id, sha256=document.sha256, page=0, quote=QUOTE
    )
    assert _resolve_any(store=store, anchor=anchor).status == "ok"
    (
        document_dir(
            courses_dir=store.courses_dir, course_id=COURSE_ID, doc_id=document.id
        )
        / "document.json"
    ).write_text(data="{not json", encoding="utf-8")

    assert _resolve_any(store=store, anchor=anchor) == AnchorResolution(
        href=f"/corsi/{KEY}/documenti/{document.id}?p=0", status="unavailable"
    )


def test_resolve_generation_corrupted_record_returns_unavailable(
    store: JobStore,
) -> None:
    generation = create_generation(
        courses_dir=store.courses_dir,
        course_id=COURSE_ID,
        request=GenerationRequest(format=GenerationFormat.OPEN, count=1),
    )
    anchor = GenerationAnchor(generation_id=generation.id, question_index=0)
    assert _resolve_any(store=store, anchor=anchor).status == "ok"
    generation_path(
        courses_dir=store.courses_dir, course_id=COURSE_ID, gen_id=generation.id
    ).write_text(data="{not json", encoding="utf-8")

    assert _resolve_any(store=store, anchor=anchor) == AnchorResolution(
        href=f"/corsi/{KEY}/generazioni/{generation.id}", status="unavailable"
    )


def _resolve_any(
    store: JobStore, anchor: DocumentAnchor | GenerationAnchor
) -> AnchorResolution:
    return resolve_anchor(anchor=anchor, store=store, course_id=COURSE_ID, key=KEY)
