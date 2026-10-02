import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import cast
from uuid import uuid4

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import JsonValue
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from sbobina.settings import Settings
from sbobina.web import sse
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobRecord, JobStage, JobStatus
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
TEST_TIMEOUT_S = 3.0
TEST_POLL_S = 0.005
TEST_PING_S = 0.025


@dataclass
class LiveStream:
    store: JobStore
    job: JobRecord
    frames: Queue[str]

    def receive(self) -> tuple[str, dict[str, JsonValue]]:
        frame = self.frames.get(timeout=TEST_TIMEOUT_S)
        fields = dict(line.split(": ", 1) for line in frame.splitlines() if line)
        return fields["event"], cast(dict[str, JsonValue], json.loads(fields["data"]))

    def receive_report(self) -> tuple[str, dict[str, JsonValue]]:
        # write() changes job.json before progress.json, as the supervisor does:
        # a poll between the two sees the new stage with no report yet. That
        # frame appears or not depending on timing, so skip it here, together
        # with any keep-alive ping that lands between the two writes.
        deadline = time.monotonic() + TEST_TIMEOUT_S
        while True:
            frame = self.frames.get(timeout=max(0.0, deadline - time.monotonic()))
            if frame.startswith(":"):
                continue
            fields = dict(line.split(": ", 1) for line in frame.splitlines() if line)
            data = cast(dict[str, JsonValue], json.loads(fields["data"]))
            if data["progress"] is not None:
                return fields["event"], data
            assert (data["speed"], data["eta_s"]) == (None, None)

    def write(self, fraction: float, stage: str = "transcribing") -> None:
        # Like the supervisor: job.json names the stage before the child reports.
        self.job = self.store.update(
            record=self.job.model_copy(
                update={"status": JobStatus.RUNNING, "stage": JobStage(stage)}
            )
        )
        self.store.write_progress(
            job_id=str(self.job.id),
            progress={
                "stage": stage,
                "progress": fraction,
                "audio_s": 40.0 if stage == "transcribing" else 0.0,
                "elapsed_s": 10.0,
            },
        )

    def finish(self, status: JobStatus = JobStatus.DONE) -> None:
        self.store.update(
            record=self.job.model_copy(
                update={"status": status, "stage": JobStage.DONE}
            )
        )


def _collect_lines(app: FastAPI, job_id: str, frames: Queue[str]) -> list[str]:
    async def observe(scope: Scope, receive: Receive, send: Send) -> None:
        async def capture(message: Message) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                frames.put(message["body"].decode())
            await send(message)

        with anyio.fail_after(TEST_TIMEOUT_S):
            await app(scope, receive, capture)

    with TestClient(observe, base_url=BASE_URL).stream(
        "GET", f"/api/v1/jobs/{job_id}/events"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        return list(response.iter_lines())


@contextmanager
def _open_stream(app: FastAPI, job: JobRecord) -> Iterator[LiveStream]:
    stream = LiveStream(store=app.state.job_store, job=job, frames=Queue())
    # TestClient buffers until completion; observe real ASGI frames to coordinate writes.
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_collect_lines, app, str(job.id), stream.frames)
        try:
            yield stream
        finally:
            stream.finish()
        lines = future.result(timeout=TEST_TIMEOUT_S)
        assert "event: progress" in lines
        assert lines[-3] == "event: end"
        assert json.loads(lines[-2].removeprefix("data: "))["status"] == "done"


@pytest.fixture
def job_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FastAPI, JobRecord]:
    monkeypatch.setattr(sse, "POLL_INTERVAL_S", TEST_POLL_S)
    monkeypatch.setattr(sse, "PING_INTERVAL_S", TEST_TIMEOUT_S)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    store: JobStore = app.state.job_store
    job = store.create(config=JobConfig())
    return app, job


def test_events_progress_updates_emit_increasing_values(
    job_app: tuple[FastAPI, JobRecord],
) -> None:
    app, job = job_app
    with _open_stream(app=app, job=job) as stream:
        assert stream.receive() == (
            "progress",
            {
                "status": "queued",
                "stage": "queued",
                "progress": None,
                "elapsed_s": None,
                "speed": None,
                "eta_s": None,
                "notice": None,
            },
        )
        values = []
        for fraction in (0.2, 0.5, 0.9):
            stream.write(fraction=fraction)
            event, data = stream.receive_report()
            assert event == "progress"
            values.append(data["progress"])
        assert values == [0.2, 0.5, 0.9]


def test_events_identical_progress_emits_ping_without_duplicate(
    job_app: tuple[FastAPI, JobRecord], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "PING_INTERVAL_S", TEST_PING_S)
    app, job = job_app
    with _open_stream(app=app, job=job) as stream:
        assert stream.receive()[1]["status"] == "queued"
        stream.write(fraction=0.5)
        assert stream.receive_report()[1]["progress"] == 0.5
        stream.write(fraction=0.5)
        assert stream.frames.get(timeout=TEST_TIMEOUT_S) == ": ping\n\n"
        stream.write(fraction=0.75)
        assert stream.receive_report()[1]["progress"] == 0.75


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "interrupted"])
def test_events_terminal_status_emits_end_and_closes(
    job_app: tuple[FastAPI, JobRecord], status: str
) -> None:
    app, job = job_app
    frames: Queue[str] = Queue()
    stream = LiveStream(store=app.state.job_store, job=job, frames=frames)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_collect_lines, app, str(job.id), frames)
        assert stream.receive()[1]["status"] == "queued"
        stream.finish(status=JobStatus(status))
        assert stream.receive()[1]["status"] == status
        assert stream.receive() == ("end", {"status": status, "stage": "done"})
        lines = future.result(timeout=TEST_TIMEOUT_S)
    assert lines.count("event: progress") == 2
    assert lines.count("event: end") == 1
    assert json.loads(lines[-2].removeprefix("data: ")) == {
        "status": status,
        "stage": "done",
    }


@pytest.mark.parametrize("job_id", ["invalid", str(uuid4())])
def test_events_missing_job_returns_json_404_before_streaming(
    job_app: tuple[FastAPI, JobRecord], job_id: str
) -> None:
    app, _ = job_app
    with TestClient(app, base_url=BASE_URL).stream(
        "GET", f"/api/v1/jobs/{job_id}/events"
    ) as response:
        response.read()
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": f"Job {job_id} non trovato"}
    }


def test_events_stage_progress_reports_speed_and_eta(
    job_app: tuple[FastAPI, JobRecord],
) -> None:
    app, job = job_app
    with _open_stream(app=app, job=job) as stream:
        assert stream.receive()[1]["stage"] == "queued"
        stream.write(fraction=0.25)
        event, data = stream.receive_report()
        assert event == "progress"
        assert (data["stage"], data["speed"], data["eta_s"]) == (
            "transcribing",
            4.0,
            30.0,
        )
        stream.write(fraction=0.5, stage="correcting")
        event, data = stream.receive_report()
        assert event == "progress"
        assert (data["stage"], data["speed"], data["eta_s"]) == (
            "correcting",
            None,
            10.0,
        )


@pytest.mark.parametrize("fraction,elapsed", [(0.0, 10.0), (0.5, 0.0)])
def test_events_zero_progress_or_time_does_not_invent_eta(
    job_app: tuple[FastAPI, JobRecord], fraction: float, elapsed: float
) -> None:
    app, job = job_app
    with _open_stream(app=app, job=job) as stream:
        assert stream.receive()[1]["progress"] is None
        stream.job = stream.store.update(
            record=job.model_copy(
                update={"status": JobStatus.RUNNING, "stage": JobStage.TRANSCRIBING}
            )
        )
        stream.receive()
        stream.store.write_progress(
            job_id=str(job.id),
            progress={
                "stage": "transcribing",
                "progress": fraction,
                "audio_s": 40.0,
                "elapsed_s": elapsed,
            },
        )
        event, data = stream.receive()
        assert event == "progress"
        assert data["progress"] == fraction
        assert data["elapsed_s"] == elapsed
        assert data["speed"] == (4.0 if elapsed else None)
        assert data["eta_s"] is None


def test_stream_disconnected_request_stops_after_current_progress(
    job_app: tuple[FastAPI, JobRecord],
) -> None:
    app, job = job_app

    async def scenario() -> None:
        disconnected = False

        async def receive() -> Message:
            return {"type": "http.disconnect" if disconnected else "http.request"}

        request = Request(scope={"type": "http"}, receive=receive)
        stream = sse._stream(
            request=request, job_store=app.state.job_store, job_id=str(job.id)
        )
        with anyio.fail_after(TEST_TIMEOUT_S):
            assert "event: progress" in await anext(stream)
            disconnected = True
            with pytest.raises(StopAsyncIteration):
                await anext(stream)

    anyio.run(scenario)


@pytest.mark.parametrize(
    "case",
    [
        ("transcribing", 0.25, 10.0, 4.0, 30.0),
        ("correcting", 0.5, 10.0, None, 10.0),
        ("transcribing", 0.0, 10.0, 4.0, None),
        ("transcribing", None, 10.0, 4.0, None),
        ("transcribing", 0.5, 0.0, None, None),
        ("transcribing", 1.0, 10.0, 4.0, 0.0),
    ],
)
def test_progress_payload_fraction_and_time_produce_expected_metrics(
    job_app: tuple[FastAPI, JobRecord],
    case: tuple[str, float | None, float, float | None, float | None],
) -> None:
    _, job = job_app
    stage, fraction, elapsed, speed, eta = case
    data = sse._progress_payload(
        record=job.model_copy(update={"stage": JobStage(stage)}),
        progress={
            "stage": stage,
            "progress": fraction,
            "elapsed_s": elapsed,
            "audio_s": 40.0,
        },
    )
    assert (data["stage"], data["progress"], data["elapsed_s"]) == (
        stage,
        fraction,
        elapsed,
    )
    assert (data["speed"], data["eta_s"]) == (speed, eta)


def test_events_stale_progress_from_previous_stage_is_not_shown(
    job_app: tuple[FastAPI, JobRecord],
) -> None:
    app, job = job_app
    with _open_stream(app=app, job=job) as stream:
        stream.receive()
        stream.write(fraction=1.0, stage="transcribing")
        assert stream.receive_report()[1]["stage"] == "transcribing"
        # The supervisor moves to correction before the child writes anything.
        stream.job = stream.store.update(
            record=stream.job.model_copy(update={"stage": JobStage.CORRECTING})
        )

        event, data = stream.receive()

        assert event == "progress"
        assert (data["stage"], data["progress"], data["speed"]) == (
            "correcting",
            None,
            None,
        )


def test_events_job_deleted_mid_stream_ends_cleanly(
    job_app: tuple[FastAPI, JobRecord],
) -> None:
    app, job = job_app
    store: JobStore = app.state.job_store
    frames: Queue[str] = Queue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_collect_lines, app, str(job.id), frames)
        frames.get(timeout=TEST_TIMEOUT_S)
        store.delete(job_id=str(job.id))
        lines = future.result(timeout=TEST_TIMEOUT_S)

    assert lines[-3] == "event: end"
    assert json.loads(lines[-2].removeprefix("data: ")) == {
        "status": "deleted",
        "stage": None,
    }


def test_progress_payload_forwards_notice(job_app: tuple[FastAPI, JobRecord]) -> None:
    _, job = job_app
    record = job.model_copy(update={"stage": JobStage.TRANSCRIBING})
    progress: dict[str, JsonValue] = {"stage": "transcribing", "progress": 0.1}

    with_notice = sse._progress_payload(
        record=record, progress={**progress, "notice": "GPU non utilizzabile"}
    )
    without = sse._progress_payload(record=record, progress=progress)

    assert with_notice["notice"] == "GPU non utilizzabile"
    assert without["notice"] is None
