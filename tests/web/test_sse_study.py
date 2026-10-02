from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Queue
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from study_api_fixtures import client, create_job, job_store, set_study
from test_sse import TEST_POLL_S, TEST_TIMEOUT_S, LiveStream, _collect_lines

from sbobina.web import sse
from sbobina.web.job_models import JobRecord, StudyRun, StudyStatus

__all__ = ["client"]


def update_study(client: TestClient, record: JobRecord, status: StudyStatus) -> None:
    set_study(
        client=client,
        record=record,
        study=StudyRun(status=status, updated_at=datetime.now(tz=UTC)),
    )
    job_store(client=client).write_progress(
        job_id=str(record.id),
        progress={"stage": "study", "progress": 0.5, "elapsed_s": 2.0},
    )


@pytest.mark.parametrize(
    "terminal", [StudyStatus.DONE, StudyStatus.FAILED, StudyStatus.INTERRUPTED]
)
def test_events_study_keeps_done_job_open_until_study_finishes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, terminal: StudyStatus
) -> None:
    monkeypatch.setattr(target=sse, name="POLL_INTERVAL_S", value=TEST_POLL_S)
    record, _ = create_job(client=client)
    assert client.post(url=f"/api/v1/jobs/{record.id}/study").status_code == 202
    frames: Queue[str] = Queue()
    stream = LiveStream(store=job_store(client=client), job=record, frames=frames)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _collect_lines, cast(FastAPI, client.app), str(record.id), frames
        )
        try:
            event, queued = stream.receive()
            assert event == "progress" and queued["study_status"] == "queued"
            assert queued["stage"] == "study" and queued["progress"] is None
            update_study(client=client, record=record, status=StudyStatus.RUNNING)
            event, running = stream.receive_report()
            assert event == "progress" and running["study_status"] == "running"
            assert running["status"] == "done" and running["progress"] == 0.5
        finally:
            update_study(client=client, record=record, status=terminal)
        lines = future.result(timeout=TEST_TIMEOUT_S)
    assert lines[-3] == "event: end"
    assert f'"study_status": "{terminal}"' in lines[-2]
