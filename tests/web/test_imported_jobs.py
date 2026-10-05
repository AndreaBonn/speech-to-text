import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.requests import Request

from sbobina.web import work_items
from sbobina.web.errors import ConflictError
from sbobina.web.job_models import JobConfig, JobRecord, JobStage, JobStatus, WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.responses import app_error_handler
from sbobina.web.supervisor import Supervisor

RETRANSCRIPTION_MESSAGE = "Lezione importata senza audio: non si può ritrascrivere"


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


@pytest.fixture
def imported_record(store: JobStore) -> JobRecord:
    record = store.create(config=JobConfig())
    return store.update(
        record=record.model_copy(
            update={
                "status": JobStatus.DONE,
                "stage": JobStage.DONE,
                "imported": True,
                "import_id": str(uuid4()),
            }
        )
    )


def test_ensure_retranscribable_imported_lecture_raises_conflict(
    store: JobStore, imported_record: JobRecord
) -> None:
    normal = store.create(config=JobConfig())
    work_items.ensure_retranscribable(record=normal)

    with pytest.raises(ConflictError) as caught:
        work_items.ensure_retranscribable(record=imported_record)

    assert caught.value.code == "AUDIO_NOT_INCLUDED"
    assert caught.value.message == RETRANSCRIPTION_MESSAGE


def test_submit_imported_lecture_maps_to_409_audio_not_included(
    store: JobStore, imported_record: JobRecord
) -> None:
    supervisor = Supervisor(job_store=store)
    normal = store.create(config=JobConfig())
    supervisor.submit(job_id=str(normal.id))

    with pytest.raises(ConflictError) as caught:
        supervisor.submit(job_id=str(imported_record.id))

    response = asyncio.run(
        app_error_handler(request=Request(scope={"type": "http"}), exc=caught.value)
    )
    assert response.status_code == 409
    assert json.loads(s=bytes(response.body))["error"] == {
        "code": "AUDIO_NOT_INCLUDED",
        "message": RETRANSCRIPTION_MESSAGE,
    }
    assert list(supervisor._queue) == [
        WorkItem(job_id=str(normal.id), action="pipeline")
    ]
    assert store.get(job_id=str(imported_record.id)) == imported_record


def test_recover_on_boot_imported_lecture_queues_nothing_and_logs_no_error(
    store: JobStore, imported_record: JobRecord, caplog: pytest.LogCaptureFixture
) -> None:
    supervisor = Supervisor(job_store=store)

    supervisor.recover_on_boot()

    assert list(supervisor._queue) == []
    normal = store.create(config=JobConfig())
    supervisor.recover_on_boot()
    assert list(supervisor._queue) == [
        WorkItem(job_id=str(normal.id), action="pipeline")
    ]
    assert store.get(job_id=str(imported_record.id)) == imported_record
    assert caplog.records == []


def test_prepare_study_imported_lecture_with_transcript_is_ready(
    store: JobStore, imported_record: JobRecord
) -> None:
    path = store.jobs_dir / str(imported_record.id) / "audio.json"
    path.write_text(data="{}", encoding="utf-8")

    prepared = work_items.prepare_study(store=store, job_id=str(imported_record.id))

    assert prepared == imported_record
    path.unlink()
    with pytest.raises(ConflictError) as caught:
        work_items.prepare_study(store=store, job_id=str(imported_record.id))
    assert caught.value.code == "STUDY_NOT_READY"
