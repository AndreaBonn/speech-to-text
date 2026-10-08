import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from sbobina.web import supervisor
from sbobina.web.errors import JobNotCancellableError
from sbobina.web.job_models import JobConfig, JobRecord, JobStage, JobStatus
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor, SupervisorOptions

RUNNER = """
import os
import signal
import sys
import threading
import time
from pathlib import Path

stage, directory = sys.argv[1:]
path = Path(directory)
if (path / 'ignore-term').exists():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if (path / 'exit-on-eof').exists():
    threading.Thread(
        target=lambda: (sys.stdin.read(), os._exit(0)), daemon=True
    ).start()
with (path.parent / 'order.log').open('a') as stream:
    stream.write(path.name + ':' + stage + '\\n')
(path / (stage + '.started')).touch()
while (path / 'hold').exists():
    time.sleep(0.01)
code = path / (stage + '.exit')
sys.exit(int(code.read_text()) if code.exists() else 0)
"""


def wait_for(
    predicate: Callable[[], bool], timeout_s: float = 5, interval_s: float = 0.02
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Condition did not become true before timeout")
        time.sleep(interval_s)


@dataclass
class Harness:
    store: JobStore
    supervisor: Supervisor

    def create(self, correct: bool = False, hold: bool = False) -> str:
        record = self.store.create(config=JobConfig(correct=correct))
        job_id = str(record.id)
        if hold:
            (self.store.jobs_dir / job_id / "hold").touch()
        return job_id

    def record(self, job_id: str) -> JobRecord:
        return self.store.get(job_id=job_id)

    def marker(self, job_id: str, name: str) -> Path:
        return self.store.jobs_dir / job_id / name

    def finished(self, job_id: str) -> bool:
        return self.record(job_id=job_id).status == JobStatus.DONE


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    (tmp_path / "fake_runner.py").write_text(RUNNER, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    store = JobStore(data_dir=tmp_path)
    supervisor = Supervisor(
        job_store=store,
        options=SupervisorOptions(
            command=(sys.executable, "-m", "fake_runner"), terminate_timeout_s=0.1
        ),
    )
    try:
        yield Harness(store=store, supervisor=supervisor)
    finally:
        supervisor.stop()


def test_fifo_correction_and_duplicate_submit(harness: Harness) -> None:
    first = harness.create(correct=True, hold=True)
    second = harness.create()
    harness.supervisor.start()
    harness.supervisor.submit(job_id=first)
    wait_for(predicate=harness.marker(job_id=first, name="transcribe.started").exists)
    process = harness.supervisor._process
    assert process is not None
    assert harness.record(job_id=first).pid == process.pid
    assert harness.record(job_id=second).status == JobStatus.QUEUED
    harness.marker(job_id=first, name="hold").unlink()
    wait_for(predicate=lambda: harness.finished(job_id=second))
    assert process.poll() == 0
    assert harness.record(job_id=first).stage == JobStage.DONE
    assert harness.record(job_id=first).pid is None
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{first}:transcribe",
        f"{first}:correct",
        f"{second}:transcribe",
    ]


@pytest.mark.parametrize("ignore_term", [False, True])
def test_cancel_running_reaps_child(harness: Harness, ignore_term: bool) -> None:
    job_id = harness.create(correct=True, hold=True)
    if ignore_term:
        harness.marker(job_id=job_id, name="ignore-term").touch()
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)
    process = harness.supervisor._process
    assert process is not None
    started = time.monotonic()
    harness.supervisor.cancel(job_id=job_id)
    assert time.monotonic() - started < 10
    assert process.poll() is not None
    assert harness.record(job_id=job_id).status == JobStatus.CANCELLED
    assert harness.record(job_id=job_id).pid is None
    harness.supervisor.stop()
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{job_id}:transcribe"
    ]


def test_cancel_queued_and_submit_after_start(harness: Harness) -> None:
    first = harness.create(hold=True)
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=first, name="transcribe.started").exists)
    second = harness.create()
    third = harness.create()
    harness.supervisor.submit(job_id=second)
    harness.supervisor.submit(job_id=third)
    harness.supervisor.cancel(job_id=second)
    assert harness.record(job_id=second).status == JobStatus.CANCELLED
    harness.marker(job_id=first, name="hold").unlink()
    wait_for(predicate=lambda: harness.finished(job_id=third))
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{first}:transcribe",
        f"{third}:transcribe",
    ]


@pytest.mark.parametrize(
    "status",
    [JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED],
)
def test_cancel_terminal_raises(harness: Harness, status: JobStatus) -> None:
    job_id = harness.create()
    record = harness.record(job_id=job_id).model_copy(update={"status": status})
    harness.store.update(record=record)
    with pytest.raises(JobNotCancellableError) as caught:
        harness.supervisor.cancel(job_id=job_id)
    assert caught.value.code == "JOB_NOT_CANCELLABLE"
    assert harness.record(job_id=job_id).status == status


def test_recovery_interrupts_running_and_orders_all_queued(harness: Harness) -> None:
    running = harness.create()
    harness.store.update(
        record=harness.record(job_id=running).model_copy(
            update={"status": JobStatus.RUNNING, "pid": 12345}
        )
    )
    output = harness.marker(job_id=running, name="audio.txt")
    output.write_text("existing transcript")
    queued = [harness.create() for _ in range(12)]
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.finished(job_id=queued[-1]))
    interrupted = harness.record(job_id=running)
    assert interrupted.status == JobStatus.INTERRUPTED
    assert interrupted.error == {"code": "SERVER_RESTARTED"}
    assert interrupted.pid is None
    assert output.read_text() == "existing transcript"
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{job_id}:transcribe" for job_id in queued
    ]


@pytest.mark.parametrize(
    ("stage", "code", "error"),
    [("transcribe", 1, "STAGE_FAILED"), ("correct", 2, "OLLAMA_UNAVAILABLE")],
)
def test_stage_failure_does_not_block_next_job(
    harness: Harness, stage: str, code: int, error: str
) -> None:
    first = harness.create(correct=True)
    harness.marker(job_id=first, name=f"{stage}.exit").write_text(str(code))
    second = harness.create()
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.finished(job_id=second))
    record = harness.record(job_id=first)
    assert record.status == JobStatus.FAILED
    assert record.error == {"code": error}
    assert record.pid is None


def test_stop_reaps_process_and_leaves_queue_for_restart(harness: Harness) -> None:
    first = harness.create(hold=True)
    second = harness.create()
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=first, name="transcribe.started").exists)
    process = harness.supervisor._process
    thread = harness.supervisor._thread
    assert process is not None and thread is not None
    harness.supervisor.stop()
    harness.supervisor.stop()
    assert process.poll() is not None
    assert process.stdin is not None and process.stdin.closed
    assert not thread.is_alive()
    assert harness.record(job_id=first).status == JobStatus.INTERRUPTED
    assert harness.record(job_id=second).status == JobStatus.QUEUED
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.finished(job_id=second))


def test_cancel_during_before_transcribe_prevents_spawn(harness: Harness) -> None:
    entered, release = Event(), Event()

    def before_transcribe() -> None:
        entered.set()
        assert release.wait(timeout=5)

    supervisor = Supervisor(
        job_store=harness.store, before_transcribe=before_transcribe
    )
    job_id = harness.create()
    try:
        supervisor.start()
        assert entered.wait(timeout=5)
        assert harness.record(job_id=job_id).status == JobStatus.RUNNING
        supervisor.cancel(job_id=job_id)
        assert harness.record(job_id=job_id).status == JobStatus.CANCELLED
    finally:
        release.set()
        supervisor.stop()
    assert supervisor._process is None
    assert harness.record(job_id=job_id).pid is None


def test_spawn_failure_marks_failed(harness: Harness) -> None:
    supervisor = Supervisor(
        job_store=harness.store,
        options=SupervisorOptions(command=("/nonexistent/sbobina-runner",)),
    )
    job_id = harness.create()
    try:
        supervisor.start()
        wait_for(
            predicate=lambda: harness.record(job_id=job_id).status == JobStatus.FAILED
        )
        assert harness.record(job_id=job_id).error == {"code": "SUPERVISOR_ERROR"}
    finally:
        supervisor.stop()


def test_job_deleted_while_queued_is_skipped_and_queue_continues(
    harness: Harness,
) -> None:
    busy = harness.create(hold=True)
    deleted = harness.create()
    kept = harness.create()
    harness.supervisor.start()
    harness.supervisor.submit(job_id=busy)
    wait_for(predicate=harness.marker(job_id=busy, name="transcribe.started").exists)
    harness.supervisor.submit(job_id=deleted)
    harness.supervisor.submit(job_id=kept)
    harness.store.delete(job_id=deleted)

    harness.marker(job_id=busy, name="hold").unlink()

    wait_for(predicate=lambda: harness.finished(job_id=kept))
    assert harness.supervisor.is_running()
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{busy}:transcribe",
        f"{kept}:transcribe",
    ]


def test_recovery_reads_every_page_of_queued_jobs(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor, "RECOVERY_PAGE_SIZE", 5)
    queued = [harness.create() for _ in range(12)]

    harness.supervisor.start()

    wait_for(predicate=lambda: all(harness.finished(job_id=j) for j in queued))
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{job_id}:transcribe" for job_id in queued
    ]


def test_start_while_running_keeps_the_same_worker(harness: Harness) -> None:
    harness.supervisor.start()
    worker = harness.supervisor._thread

    harness.supervisor.start()

    assert harness.supervisor._thread is worker


def test_recover_on_boot_while_running_raises(harness: Harness) -> None:
    harness.supervisor.start()

    with pytest.raises(RuntimeError, match="Cannot recover"):
        harness.supervisor.recover_on_boot()


def test_stop_lets_a_child_exit_on_stdin_close_without_terminating(
    harness: Harness,
) -> None:
    # A generous reap window: the child needs time to see EOF under CI load,
    # and missing it would fall back to SIGTERM and fail for the wrong reason.
    patient = Supervisor(
        job_store=harness.store,
        options=SupervisorOptions(
            command=(sys.executable, "-m", "fake_runner"), terminate_timeout_s=5.0
        ),
    )
    job_id = harness.create(hold=True)
    harness.marker(job_id=job_id, name="exit-on-eof").touch()
    patient.start()
    try:
        wait_for(
            predicate=harness.marker(job_id=job_id, name="transcribe.started").exists
        )
        process = patient._process
        assert process is not None
    finally:
        patient.stop()

    assert process.returncode == 0  # exited by itself, not by SIGTERM (-15)
    assert harness.record(job_id=job_id).status == JobStatus.INTERRUPTED


def test_job_no_longer_queued_when_dequeued_is_skipped(harness: Harness) -> None:
    busy = harness.create(hold=True)
    changed = harness.create()
    kept = harness.create()
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=busy, name="transcribe.started").exists)
    harness.store.update(
        record=harness.record(job_id=changed).model_copy(
            update={"status": JobStatus.CANCELLED}
        )
    )

    harness.marker(job_id=busy, name="hold").unlink()

    wait_for(predicate=lambda: harness.finished(job_id=kept))
    assert harness.record(job_id=changed).status == JobStatus.CANCELLED
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{busy}:transcribe",
        f"{kept}:transcribe",
    ]


def test_job_deleted_while_running_does_not_stop_the_queue(harness: Harness) -> None:
    busy = harness.create(hold=True)
    kept = harness.create()
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=busy, name="transcribe.started").exists)

    harness.store.delete(job_id=busy)

    wait_for(predicate=lambda: harness.finished(job_id=kept))
    assert harness.supervisor.is_running()


@pytest.mark.parametrize("has_stdin", [True, False], ids=["piped", "no-stdin"])
def test_release_process_forgets_the_child_and_closes_its_stdin(
    tmp_path: Path, has_stdin: bool
) -> None:
    owner = Supervisor(job_store=JobStore(data_dir=tmp_path))
    process = subprocess.Popen(
        args=[sys.executable, "-c", "pass"],
        stdin=subprocess.PIPE if has_stdin else None,
    )
    process.wait(timeout=5)
    owner._process = process

    owner._release_process(process=process)

    assert owner._process is None
    assert (process.stdin is not None and process.stdin.closed) is has_stdin
