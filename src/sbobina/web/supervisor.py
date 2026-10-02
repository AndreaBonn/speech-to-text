import logging
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Thread

from sbobina.web.job_models import JobRecord, JobStage, JobStatus, WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.processes import _child_env, _reap, _spawn
from sbobina.web.work_items import (
    action_status,
    cancel_action,
    finish_action,
    prepare_study,
    recover_queue,
    transition,
)

__all__ = ["Supervisor", "SupervisorOptions", "_child_env"]

logger = logging.getLogger("sbobina")
DEFAULT_COMMAND = (sys.executable, "-m", "sbobina.web.stage_runner")
TERMINATE_TIMEOUT_S = 5.0
RECOVERY_PAGE_SIZE = 100
OLLAMA_UNAVAILABLE_EXIT = 2
CHILD_LOG_NAME = "child.log"
STAGE_COMMANDS = {
    JobStage.TRANSCRIBING: "transcribe",
    JobStage.CORRECTING: "correct",
    JobStage.STUDY: "study",
}


@dataclass(frozen=True)
class SupervisorOptions:
    command: tuple[str, ...] = DEFAULT_COMMAND
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S


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
        self._queue: deque[WorkItem] = deque()
        self._thread: Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._active: WorkItem | None = None
        self._stopping = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._condition:
            if self.is_running():
                return
            self.recover_on_boot()
            self._stopping = False
            self._thread = Thread(target=self._work, name="sbobina-supervisor")
            self._thread.start()

    def recover_on_boot(self) -> None:
        with self._condition:
            if self.is_running():
                raise RuntimeError("Cannot recover while the worker is running")
            self._queue = recover_queue(store=self._store, page_size=RECOVERY_PAGE_SIZE)

    def submit(self, job_id: str) -> None:
        with self._condition:
            record = self._store.get(job_id=job_id)
            item = WorkItem(job_id=str(record.id), action="pipeline")
            if record.status == JobStatus.QUEUED and item not in self._queue:
                self._queue.append(item)
                self._condition.notify()

    def submit_study(self, job_id: str) -> JobRecord:
        with self._condition:
            record = prepare_study(store=self._store, job_id=job_id)
            item = WorkItem(job_id=str(record.id), action="study")
            queued = self._store.update(
                record=transition(record=record, item=item, status=JobStatus.QUEUED)
            )
            self._queue.append(item)
            self._condition.notify()
            return queued

    def cancel(self, job_id: str) -> None:
        with self._condition:
            record = self._store.get(job_id=job_id)
            item, status = cancel_action(record=record)
            if item in self._queue:
                self._queue.remove(item)
            if self._active == item:
                self._stop_process(graceful=False)
            self._store.update(
                record=transition(record=record, item=item, status=status)
            )

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._stop_process(graceful=True)
            if (item := self._active) is not None:
                finish_action(
                    store=self._store, item=item, status=JobStatus.INTERRUPTED
                )
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

    def _next_job(self) -> WorkItem | None:
        """Claim a queued action under the same lock used for submission and cancel."""
        with self._condition:
            while True:
                self._condition.wait_for(
                    predicate=lambda: self._stopping or bool(self._queue)
                )
                if self._stopping:
                    return None
                item = self._queue.popleft()
                if self._claim(item=item):
                    return item

    def _claim(self, item: WorkItem) -> bool:
        try:
            record = self._store.get(job_id=item.job_id)
        except Exception:
            logger.exception("Job %s non leggibile, saltato", item.job_id)
            return False
        if action_status(record=record, item=item) != JobStatus.QUEUED:
            return False
        self._store.update(
            record=transition(record=record, item=item, status=JobStatus.RUNNING)
        )
        self._active = item
        return True

    def _work(self) -> None:
        while (item := self._next_job()) is not None:
            try:
                self._execute(item=item)
            except Exception:
                logger.exception("Supervisione fallita per il job %s", item.job_id)
                with self._condition:
                    self._stop_process(graceful=False)
                    finish_action(
                        store=self._store,
                        item=item,
                        status=JobStatus.FAILED,
                        code="SUPERVISOR_ERROR",
                    )
            finally:
                with self._condition:
                    self._active = None

    def _execute(self, item: WorkItem) -> None:
        record = self._store.get(job_id=item.job_id)
        stages = [JobStage.STUDY]
        if item.action == "pipeline":
            if self._before_transcribe is not None:
                self._before_transcribe()
            stages = [JobStage.TRANSCRIBING]
            if record.config.correct:
                stages.append(JobStage.CORRECTING)
        for stage in stages:
            if not self._run_stage(item=item, stage=stage):
                return
        with self._condition:
            finish_action(store=self._store, item=item, status=JobStatus.DONE)

    def _run_stage(self, item: WorkItem, stage: JobStage) -> bool:
        with self._condition:
            record = self._store.get(job_id=item.job_id)
            if (
                self._stopping
                or action_status(record=record, item=item) != JobStatus.RUNNING
            ):
                return False
            process = self._launch(record=record, stage=stage)
        return_code = process.wait()
        with self._condition:
            if process.stdin is not None:
                process.stdin.close()
            if self._process is process:
                self._process = None
            record = self._store.get(job_id=item.job_id)
            if action_status(record=record, item=item) != JobStatus.RUNNING:
                return False
            if return_code != 0:
                code = (
                    "OLLAMA_UNAVAILABLE"
                    if stage in (JobStage.CORRECTING, JobStage.STUDY)
                    and return_code == OLLAMA_UNAVAILABLE_EXIT
                    else "STAGE_FAILED"
                )
                finish_action(
                    store=self._store, item=item, status=JobStatus.FAILED, code=code
                )
                return False
            return True

    def _launch(self, record: JobRecord, stage: JobStage) -> subprocess.Popen[bytes]:
        directory = self._store.jobs_dir / str(record.id)
        process = _spawn(
            command=[*self._options.command, STAGE_COMMANDS[stage], str(directory)],
            log_path=directory / CHILD_LOG_NAME,
        )
        self._process = process
        update: dict[str, object] = {"pid": process.pid}
        if stage != JobStage.STUDY:
            update["stage"] = stage
        self._store.update(record=record.model_copy(update=update))
        return process
