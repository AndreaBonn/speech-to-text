import pytest
from embedding_trigger_fixtures import (
    extraction_app,
    install_ocr_child,
    installed_embedding,
    prepare_extraction,
)
from fastapi import FastAPI
from ocr_fixtures import COURSE_KEY, DOC_ID, add_scanned_document
from test_supervisor import Harness, harness

from sbobina.course_registry import find_by_key, get_or_create
from sbobina.document_models import DocumentStatus
from sbobina.web.document_store import read_document
from sbobina.web.embedding_store import EmbeddingStatus, load_embed
from sbobina.web.extraction_worker import ExtractionItem
from sbobina.web.job_models import JobConfig, JobStage, JobStatus, LectureMeta, WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor

__all__ = ["extraction_app", "harness", "installed_embedding"]


def _embed_items(supervisor: Supervisor) -> list[WorkItem]:
    return [item for item in supervisor._queue if item.action == "embed"]


def _assert_queued(supervisor: Supervisor, course_id: str) -> None:
    assert _embed_items(supervisor=supervisor) == [
        WorkItem(job_id=course_id, action="embed", course_id=course_id)
    ]
    run = load_embed(course_dir=supervisor._store.courses_dir / course_id)
    assert run is not None
    assert run.status is EmbeddingStatus.QUEUED


def _complete_pipeline(
    harness: Harness, config: JobConfig, course: str | None = None
) -> None:
    record = harness.store.create(config=config)
    harness.store.write_meta(job_id=str(record.id), meta=LectureMeta(course=course))
    item = WorkItem(job_id=str(record.id), action="pipeline")
    assert harness.supervisor._claim(item=item)
    harness.supervisor._execute(item=item)
    assert harness.record(job_id=str(record.id)).status is JobStatus.DONE


def _document_status(store: JobStore, course_id: str) -> DocumentStatus:
    return read_document(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=DOC_ID
    ).status


@pytest.mark.parametrize(
    ("config", "course"), [(JobConfig(), "Fisica"), (JobConfig(subject="Fisica"), None)]
)
def test_pipeline_completion_enqueues_named_course_only(
    harness: Harness, installed_embedding: None, config: JobConfig, course: str | None
) -> None:
    registered = get_or_create(
        courses_dir=harness.store.courses_dir, key=COURSE_KEY, label="Fisica"
    )

    _complete_pipeline(harness=harness, config=JobConfig())
    assert _embed_items(supervisor=harness.supervisor) == []
    _complete_pipeline(harness=harness, config=config, course=course)

    _assert_queued(supervisor=harness.supervisor, course_id=registered.id)


def test_extraction_completion_enqueues_ready_document_only(
    extraction_app: FastAPI, installed_embedding: None
) -> None:
    store: JobStore = extraction_app.state.job_store
    supervisor: Supervisor = extraction_app.state.supervisor
    course_id, directory = add_scanned_document(courses_dir=store.courses_dir)
    marker = directory / "no-text"
    marker.touch()
    worker = extraction_app.state.extraction_worker
    item = ExtractionItem(course_id=course_id, doc_id=DOC_ID)

    prepare_extraction(store=store, course_id=course_id, doc_id=DOC_ID)
    worker._run_one(item=item)
    assert (
        _document_status(store=store, course_id=course_id)
        is DocumentStatus.READY_NO_TEXT
    )
    assert _embed_items(supervisor=supervisor) == []
    marker.unlink()
    prepare_extraction(store=store, course_id=course_id, doc_id=DOC_ID)
    worker._run_one(item=item)

    assert _document_status(store=store, course_id=course_id) is DocumentStatus.READY
    _assert_queued(supervisor=supervisor, course_id=course_id)


def test_ocr_completion_enqueues_ready_document_only(
    harness: Harness, installed_embedding: None
) -> None:
    course_id, directory = add_scanned_document(courses_dir=harness.store.courses_dir)
    install_ocr_child(harness=harness)
    marker = directory / "no-text"
    marker.touch()
    item = WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id)

    harness.supervisor._execute(item=item)
    assert (
        _document_status(store=harness.store, course_id=course_id)
        is DocumentStatus.READY_NO_TEXT
    )
    assert _embed_items(supervisor=harness.supervisor) == []
    marker.unlink()
    harness.supervisor._execute(item=item)

    assert (
        _document_status(store=harness.store, course_id=course_id)
        is DocumentStatus.READY
    )
    _assert_queued(supervisor=harness.supervisor, course_id=course_id)


def test_pipeline_completion_registers_course_before_enqueue(
    harness: Harness, installed_embedding: None
) -> None:
    _complete_pipeline(harness=harness, config=JobConfig(subject="Fisica"))

    registered = find_by_key(courses_dir=harness.store.courses_dir, key=COURSE_KEY)
    assert registered is not None
    _assert_queued(supervisor=harness.supervisor, course_id=registered.id)


def test_pipeline_cancel_after_child_completion_skips_embed(
    harness: Harness, installed_embedding: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = get_or_create(
        courses_dir=harness.store.courses_dir, key=COURSE_KEY, label="Fisica"
    )
    config = JobConfig(subject="Fisica")
    cancelled = harness.store.create(config=config)
    run_stage = harness.supervisor._run_stage

    def cancel_completed_stage(item: WorkItem, stage: JobStage) -> bool:
        completed = run_stage(item=item, stage=stage)
        if item.job_id == str(cancelled.id):
            harness.supervisor.cancel(job_id=item.job_id)
        return completed

    monkeypatch.setattr(harness.supervisor, "_run_stage", cancel_completed_stage)
    item = WorkItem(job_id=str(cancelled.id), action="pipeline")
    assert harness.supervisor._claim(item=item)
    harness.supervisor._execute(item=item)

    assert harness.record(job_id=str(cancelled.id)).status is JobStatus.CANCELLED
    assert _embed_items(supervisor=harness.supervisor) == []
    _complete_pipeline(harness=harness, config=config)
    _assert_queued(supervisor=harness.supervisor, course_id=registered.id)
