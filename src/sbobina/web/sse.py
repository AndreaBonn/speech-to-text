import json
from collections.abc import AsyncIterator
from functools import partial

import anyio
import anyio.to_thread
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import JsonValue

from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobRecord, JobStatus
from sbobina.web.job_store import JobStore

router = APIRouter(prefix="/api/v1/jobs")
POLL_INTERVAL_S = 1.0
PING_INTERVAL_S = 15.0
TERMINAL_STATUSES = (
    JobStatus.DONE,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.INTERRUPTED,
)
CHANGE_FIELDS = ("status", "stage", "progress", "elapsed_s")
DELETED_END: dict[str, JsonValue] = {"status": "deleted", "stage": None}


def _number(value: JsonValue) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _progress_payload(
    record: JobRecord, progress: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    # job.json is authoritative: progress.json can still hold the previous
    # stage's final numbers until the next child writes its first update.
    stage = record.stage
    if progress.get("stage") != stage:
        progress = {}
    elapsed = _number(value=progress.get("elapsed_s"))
    fraction = _number(value=progress.get("progress"))
    audio = _number(value=progress.get("audio_s"))
    speed = eta = None
    if elapsed is not None and elapsed > 0:
        if stage == "transcribing" and audio is not None:
            speed = audio / elapsed
        if fraction is not None and fraction > 0:
            eta = elapsed * (1 - fraction) / fraction
    return {
        "status": record.status,
        "stage": stage,
        "progress": fraction,
        "elapsed_s": elapsed,
        "speed": speed,
        "eta_s": eta,
    }


def _read_payload(job_store: JobStore, job_id: str) -> dict[str, JsonValue]:
    return _progress_payload(
        record=job_store.get(job_id=job_id),
        progress=job_store.read_progress(job_id=job_id),
    )


def _encode_event(event: str, data: dict[str, JsonValue]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(
    request: Request, job_store: JobStore, job_id: str
) -> AsyncIterator[str]:
    previous = None
    last_sent = anyio.current_time()
    while not await request.is_disconnected():
        try:
            data = await anyio.to_thread.run_sync(
                partial(_read_payload, job_store=job_store, job_id=job_id)
            )
        except NotFoundError:
            # Deleted while streaming: headers are already sent, so close with
            # an explicit end instead of an aborted connection.
            yield _encode_event(event="end", data=DELETED_END)
            return
        signature = tuple(data[field] for field in CHANGE_FIELDS)
        if signature != previous:
            yield _encode_event(event="progress", data=data)
            previous = signature
            last_sent = anyio.current_time()
        if data["status"] in TERMINAL_STATUSES:
            yield _encode_event(
                event="end", data={"status": data["status"], "stage": data["stage"]}
            )
            return
        if anyio.current_time() - last_sent >= PING_INTERVAL_S:
            yield ": ping\n\n"
            last_sent = anyio.current_time()
        await anyio.sleep(POLL_INTERVAL_S)


@router.get("/{job_id}/events", response_class=StreamingResponse)
async def job_events(request: Request, job_id: str) -> StreamingResponse:
    job_store: JobStore = request.app.state.job_store
    await anyio.to_thread.run_sync(partial(job_store.get, job_id=job_id))
    # Plain StreamingResponse: the SSE wire format is two lines (_encode_event),
    # and the job must 404 as JSON before the stream opens.
    # https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse
    return StreamingResponse(
        content=_stream(request=request, job_store=job_store, job_id=job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
