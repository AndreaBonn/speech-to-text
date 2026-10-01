import logging
import os
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Thread

from sbobina.web.errors import JobNotCancellableError, NotFoundError
from sbobina.web.job_models import JobRecord, JobStage, JobStatus
from sbobina.web.job_store import JobStore

logger = logging.getLogger("sbobina")
DEFAULT_COMMAND = (sys.executable, "-m", "sbobina.web.stage_runner")
TERMINATE_TIMEOUT_S = 5.0
RECOVERY_PAGE_SIZE = 100
OLLAMA_UNAVAILABLE_EXIT = 2
CHILD_LOG_NAME = "child.log"


@dataclass(frozen=True)
class SupervisorOptions:
    command: tuple[str, ...] = DEFAULT_COMMAND
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S


def _child_env() -> dict[str, str]:
    # Force UTF-8 I/O in the child: a Windows pipe/file otherwise uses the
    # system codepage and raises UnicodeEncodeError on accented log text
    # (BASIS: inferred).
    env = dict(os.environ)
    if sys.platform == "win32":
        env["PYTHONUTF8"] = "1"
    return env


def _spawn(command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    # Redirected to a file, never piped: a pipe nobody drains blocks the
    # child once its OS buffer fills.
    with log_path.open("a", encoding="utf-8") as log_file:
        if sys.platform == "win32":
            return subprocess.Popen(
                args=command,
                stdin=subprocess.PIPE,
                stdout=log_file,
                stderr=log_file,
                env=_child_env(),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        return subprocess.Popen(
            args=command,
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=log_file,
            env=_child_env(),
            start_new_session=True,
        )


def _reap(process: subprocess.Popen[bytes], timeout_s: float, graceful: bool) -> None:
    try:
        if graceful and process.stdin is not None:
            process.stdin.close()
            try:
                process.wait(timeout=timeout_s)
                return
            except subprocess.TimeoutExpired:
                logger.info(
                    "Il processo %s non si è fermato alla chiusura stdin", process.pid
                )
        process.terminate()
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("Arresto forzato del processo %s", process.pid)
            process.kill()
            process.wait()
    finally:
        if process.stdin is not None:
            process.stdin.close()


class Supervisor:
    def __init__(
        self,
        job_store: JobStore,
        before_transcribe: Callable[[], None] | None = None,
        options: SupervisorOptions | None = None,
    ) -> None:
        self._store = job_store
        self._before_transcribe = before_transcribe
        self._options = options if options is not None else SupervisorOptions()
        self._condition = Condition()
        self._queue: deque[str] = deque()
        self._thread: Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._active: str | None = None
        self._stopping = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self.recover_on_boot()
            self._stopping = False
            self._thread = Thread(target=self._work, name="sbobina-supervisor")
            self._thread.start()

    def recover_on_boot(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Cannot recover while the worker is running")
            page = self._store.list(page=1, per_page=RECOVERY_PAGE_SIZE)
            records = list(page.items)
            for number in range(2, page.total_pages + 1):
                records.extend(
                    self._store.list(page=number, per_page=RECOVERY_PAGE_SIZE).items
                )
            self._queue.clear()
            for record in sorted(records, key=lambda item: item.created_at):
                if record.status == JobStatus.RUNNING:
                    interrupted = record.model_copy(
                        update={
                            "status": JobStatus.INTERRUPTED,
                            "pid": None,
                            "error": {"code": "SERVER_RESTARTED"},
                        }
                    )
                    self._store.update(record=interrupted)
                elif record.status == JobStatus.QUEUED:
                    self._queue.append(str(record.id))

    def submit(self, job_id: str) -> None:
        with self._condition:
            record = self._store.get(job_id=job_id)
            if record.status == JobStatus.QUEUED and job_id not in self._queue:
                self._queue.append(job_id)
                self._condition.notify()

    def cancel(self, job_id: str) -> None:
        with self._condition:
            record = self._store.get(job_id=job_id)
            if record.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise JobNotCancellableError(job_id=job_id)
            if job_id in self._queue:
                self._queue.remove(job_id)
            if self._active == job_id:
                self._stop_process(graceful=False)
            self._store.update(
                record=record.model_copy(
                    update={"status": JobStatus.CANCELLED, "pid": None}
                )
            )

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._stop_process(graceful=True)
            if self._active is not None:
                self._finish(job_id=self._active, status=JobStatus.INTERRUPTED)
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join()

    def _stop_process(self, graceful: bool) -> None:
        if self._process is not None:
            _reap(
                process=self._process,
                timeout_s=self._options.terminate_timeout_s,
                graceful=graceful,
            )
            self._process = None

    def _next_job(self) -> JobRecord | None:
        """Pop the next job and mark it running in one lock hold; None means stop.

        Claiming under the same lock as ``popleft`` leaves no window in which a
        concurrent ``submit`` sees the job as queued but absent from the queue.
        """
        with self._condition:
            while True:
                self._condition.wait_for(
                    predicate=lambda: self._stopping or bool(self._queue)
                )
                if self._stopping:
                    return None
                job_id = self._queue.popleft()
                try:
                    record = self._store.get(job_id=job_id)
                except Exception:
                    # Deleted or unreadable job: skip it, the queue must go on.
                    logger.exception("Job %s non leggibile, saltato", job_id)
                    continue
                if record.status != JobStatus.QUEUED:
                    continue
                self._active = job_id
                running = record.model_copy(
                    update={"status": JobStatus.RUNNING, "error": None}
                )
                self._store.update(record=running)
                return running

    def _work(self) -> None:
        while (record := self._next_job()) is not None:
            job_id = str(record.id)
            try:
                self._execute(record=record)
            except Exception:
                logger.exception("Supervisione fallita per il job %s", job_id)
                with self._condition:
                    self._stop_process(graceful=False)
                    self._finish(
                        job_id=job_id, status=JobStatus.FAILED, code="SUPERVISOR_ERROR"
                    )
            finally:
                with self._condition:
                    self._active = None

    def _execute(self, record: JobRecord) -> None:
        job_id = str(record.id)
        if self._before_transcribe is not None:
            self._before_transcribe()
        if not self._run_stage(job_id=job_id, stage=JobStage.TRANSCRIBING):
            return
        if record.config.correct and not self._run_stage(
            job_id=job_id, stage=JobStage.CORRECTING
        ):
            return
        with self._condition:
            self._finish(job_id=job_id, status=JobStatus.DONE)

    def _run_stage(self, job_id: str, stage: JobStage) -> bool:
        with self._condition:
            record = self._store.get(job_id=job_id)
            if self._stopping or record.status != JobStatus.RUNNING:
                return False
            process = self._launch(record=record, stage=stage)
        return_code = process.wait()
        with self._condition:
            if process.stdin is not None:
                process.stdin.close()
            if self._process is process:
                self._process = None
            if self._store.get(job_id=job_id).status != JobStatus.RUNNING:
                return False
            if return_code != 0:
                code = "STAGE_FAILED"
                if (
                    stage == JobStage.CORRECTING
                    and return_code == OLLAMA_UNAVAILABLE_EXIT
                ):
                    code = "OLLAMA_UNAVAILABLE"
                self._finish(job_id=job_id, status=JobStatus.FAILED, code=code)
                return False
            return True

    def _launch(self, record: JobRecord, stage: JobStage) -> subprocess.Popen[bytes]:
        name = "transcribe" if stage == JobStage.TRANSCRIBING else "correct"
        directory: Path = self._store.jobs_dir / str(record.id)
        process = _spawn(
            command=[*self._options.command, name, str(directory)],
            log_path=directory / CHILD_LOG_NAME,
        )
        self._process = process
        self._store.update(
            record=record.model_copy(update={"stage": stage, "pid": process.pid})
        )
        return process

    def _finish(self, job_id: str, status: JobStatus, code: str | None = None) -> None:
        try:
            record = self._store.get(job_id=job_id)
        except NotFoundError:
            logger.warning("Job %s rimosso dal disco durante l'esecuzione", job_id)
            return
        if record.status != JobStatus.RUNNING:
            return
        update: dict[str, object] = {
            "status": status,
            "pid": None,
            "error": {"code": code} if code is not None else None,
        }
        if status == JobStatus.DONE:
            update["stage"] = JobStage.DONE
        self._store.update(record=record.model_copy(update=update))
