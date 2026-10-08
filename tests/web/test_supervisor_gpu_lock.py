import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from test_supervisor import Harness, harness, wait_for

from sbobina.settings import TranscriptionEngine
from sbobina.user_preferences import (
    UserPreferences,
    preferences_path,
    save_preferences,
)
from sbobina.web.errors import JobNotCancellableError
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.job_models import JobConfig, JobStatus, WorkItem
from sbobina.web.transcription_gate import execute_pipeline_action

__all__ = ["harness"]


def test_execute_pipeline_action_failed_assemblyai_skips_correction(
    harness: Harness,
) -> None:
    failed = harness.store.create(
        config=JobConfig(transcription_engine="assemblyai", correct=True)
    )
    harness.store.update(record=failed.model_copy(update={"status": JobStatus.RUNNING}))
    job_id = str(failed.id)
    harness.marker(job_id=job_id, name="transcribe.exit").write_text(
        data="1", encoding="utf-8"
    )

    result = execute_pipeline_action(
        supervisor=harness.supervisor, item=WorkItem(job_id=job_id, action="pipeline")
    )

    assert result is False
    assert harness.record(job_id=job_id).status is JobStatus.FAILED
    assert harness.marker(job_id=job_id, name="transcribe.started").exists()
    assert not harness.marker(job_id=job_id, name="correct.started").exists()

    healthy = harness.store.create(
        config=JobConfig(transcription_engine="assemblyai", correct=True)
    )
    harness.store.update(
        record=healthy.model_copy(update={"status": JobStatus.RUNNING})
    )
    healthy_id = str(healthy.id)
    assert (
        execute_pipeline_action(
            supervisor=harness.supervisor,
            item=WorkItem(job_id=healthy_id, action="pipeline"),
        )
        is True
    )
    assert harness.marker(job_id=healthy_id, name="correct.started").exists()


def _reader_count(arbiter: GpuArbiter) -> int:
    with arbiter._condition:
        return arbiter._reader_count


def _writer_waiting(arbiter: GpuArbiter) -> bool:
    with arbiter._condition:
        return arbiter._writer_waiting


def test_chat_turn_blocks_pipeline_launch_until_release(harness: Harness) -> None:
    job_id = harness.create()
    arbiter = harness.supervisor._gpu_arbiter
    release_chat = Event()

    def chat() -> None:
        with arbiter.chat_turn():
            release_chat.wait(timeout=5)

    chat_thread = threading.Thread(target=chat)
    chat_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=lambda: _writer_waiting(arbiter))
    assert not harness.marker(job_id=job_id, name="transcribe.started").exists()

    release_chat.set()
    wait_for(predicate=lambda: harness.finished(job_id=job_id))
    chat_thread.join(timeout=5)
    assert not chat_thread.is_alive()


def test_transcription_stage_rejects_chat_for_its_whole_duration(
    harness: Harness,
) -> None:
    job_id = harness.create(hold=True)
    arbiter = harness.supervisor._gpu_arbiter
    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)

    with pytest.raises(GpuBusyError) as caught, arbiter.chat_turn():
        pass
    assert caught.value.stage == "transcribing"

    harness.marker(job_id=job_id, name="hold").unlink()
    wait_for(predicate=lambda: harness.finished(job_id=job_id))
    with arbiter.chat_turn():
        pass  # the GPU is free again once the stage is over


def test_lease_released_before_correcting_stage(harness: Harness) -> None:
    job_id = harness.create(correct=True, hold=True)
    arbiter = harness.supervisor._gpu_arbiter
    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)
    harness.marker(job_id=job_id, name="hold").unlink()
    wait_for(predicate=harness.marker(job_id=job_id, name="correct.started").exists)

    with arbiter._condition:
        assert not arbiter._writer_active
        assert not arbiter._writer_waiting
    with arbiter.chat_turn():
        pass

    wait_for(predicate=lambda: harness.finished(job_id=job_id))


def test_stop_during_lease_wait_does_not_deadlock(harness: Harness) -> None:
    job_id = harness.create()
    arbiter = harness.supervisor._gpu_arbiter
    release_chat = Event()

    def chat() -> None:
        with arbiter.chat_turn():
            release_chat.wait(timeout=5)

    chat_thread = threading.Thread(target=chat)
    chat_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=lambda: _writer_waiting(arbiter))

    started = time.monotonic()
    harness.supervisor.stop()
    assert time.monotonic() - started < 5
    assert harness.record(job_id=job_id).status == JobStatus.INTERRUPTED

    release_chat.set()
    chat_thread.join(timeout=5)


def test_cancel_during_lease_wait_does_not_deadlock(harness: Harness) -> None:
    job_id = harness.create()
    arbiter = harness.supervisor._gpu_arbiter
    release_chat = Event()

    def chat() -> None:
        with arbiter.chat_turn():
            release_chat.wait(timeout=5)

    chat_thread = threading.Thread(target=chat)
    chat_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=lambda: _writer_waiting(arbiter))

    started = time.monotonic()
    try:
        harness.supervisor.cancel(job_id=job_id)
    except JobNotCancellableError:
        raise AssertionError("the waiting job should still be cancellable")
    assert time.monotonic() - started < 5
    assert harness.record(job_id=job_id).status == JobStatus.CANCELLED

    release_chat.set()
    chat_thread.join(timeout=5)
    harness.supervisor.stop()


@pytest.mark.parametrize(
    ("engine", "writer_active"), [("assemblyai", False), ("whisper", True)]
)
def test_execute_pipeline_action_engine_controls_gpu_writer(
    harness: Harness, engine: TranscriptionEngine, writer_active: bool
) -> None:
    config_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sbobina"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_preferences(
        path=preferences_path(config_dir),
        preferences=UserPreferences(
            transcription_engine=engine, cloud_ack_audio=datetime.now(tz=UTC)
        ),
    )
    job_id = harness.create(hold=True)
    arbiter = harness.supervisor._gpu_arbiter
    harness.supervisor.start()
    harness.supervisor.submit(job_id=job_id)
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)

    with arbiter._condition:
        assert arbiter._writer_active is writer_active
    if engine == "assemblyai":
        with arbiter.chat_turn():
            assert _reader_count(arbiter=arbiter) == 1

    harness.marker(job_id=job_id, name="hold").unlink()
    wait_for(predicate=lambda: harness.finished(job_id=job_id))
