import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from study_fixtures import QUOTE, transcript_fixture

from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web.api_files import transcript_revision
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobRecord, JobStage, JobStatus, StudyRun
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(paragraph_gap_s=2.0), data_dir=tmp_path)
    # No lifespan: submit_study uses the real queue, but no worker can start.
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def job_store(client: TestClient) -> JobStore:
    store: JobStore = cast(FastAPI, client.app).state.job_store
    return store


def create_job(
    client: TestClient, status: JobStatus = JobStatus.DONE
) -> tuple[JobRecord, Path]:
    store = job_store(client=client)
    record = store.create(config=JobConfig())
    record = store.update(
        record=record.model_copy(update={"status": status, "stage": JobStage.DONE})
    )
    directory = store.jobs_dir / str(record.id)
    save_transcript(transcript=transcript_fixture(), path=directory / "audio.json")
    return record, directory


def set_study(client: TestClient, record: JobRecord, study: StudyRun) -> None:
    job_store(client=client).update(record=record.model_copy(update={"study": study}))


def write_material(directory: Path, variant: str = "original") -> dict[str, Any]:
    name = "audio.corretto.json" if variant == "corrected" else "audio.json"
    revision = transcript_revision(content=(directory / name).read_text())
    citation = {"segment_index": 1, "quote": QUOTE}
    chapter = {
        "title": "Contratto",
        "start": 10.0,
        "summary": [{"text": "La causa è illecita.", "citations": [citation]}],
        "concepts": [
            {"term": "causa", "explanation": "Causa illecita", "citations": [citation]}
        ],
        "questions": [{"question": "Com'è la causa?", "citations": [citation]}],
    }
    material = {
        "source_variant": variant,
        "source_revision": revision,
        "generated_at": "2026-10-02T10:00:00Z",
        "model": "test",
        "prompt_version": "v1",
        "chapters": [chapter],
        "discarded": [{"reason": "QUOTE_NOT_FOUND", "count": 2}],
        "failed_blocks": [{"start": 20.0, "end": 30.0}],
        "served_by": None,
    }
    (directory / "audio.studio.json").write_text(json.dumps(obj=material))
    return material
