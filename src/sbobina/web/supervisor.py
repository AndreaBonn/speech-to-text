import logging
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Thread

from sbobina.generation_models import (
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.web.generation_queue import finish_generation, recover_generations
from sbobina.web.generation_supervisor import (
    cancel_generation_item,
    claim_generation_item,
    execute_generation_action,
    mark_generation_interrupted,
    submit_generation_item,
)
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.job_models import JobRecord, JobStage, JobStatus, WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.processes import _child_env, _reap, _spawn
from sbobina.web.transcription_gate import execute_pipeline_action
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
        gpu_arbiter: GpuArbiter | None = None,
    ) -> None:
        self._store = job_store
        self._before_transcribe = before_transcribe
        self._options = options if options is not None else SupervisorOptions()
        self._gpu_arbiter = gpu_arbiter if gpu_arbiter is not None else GpuArbiter()
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
            generations = recover_generations(courses_dir=self._store.courses_dir)
            self._queue.extend(
                item for _, item in sorted(generations, key=lambda entry: entry[0])
            )

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
                self._gpu_arbiter.cancel_wait()
                self._stop_process(graceful=False)
            self._store.update(
                record=transition(record=record, item=item, status=status)
            )

    def submit_generation(
        self, course_key: str, request: GenerationRequest
    ) -> GenerationRecord:
        with self._condition:
            record, item = submit_generation_item(
                store=self._store, course_key=course_key, request=request
            )
            self._queue.append(item)
            self._condition.notify()
            return record

    def cancel_generation(self, course_key: str, gen_id: str) -> None:
        with self._condition:
            item = cancel_generation_item(
                store=self._store, course_key=course_key, gen_id=gen_id
            )
            if item in self._queue:
                self._queue.remove(item)
            if self._active == item:
                self._stop_process(graceful=False)
            mark_generation_interrupted(store=self._store, item=item)

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._gpu_arbiter.cancel_wait()
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

    def _release_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdin is not None:
            process.stdin.close()
        if self._process is process:
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
            claimed = (
                claim_generation_item(store=self._store, item=item)
                if item.action == "generation"
                else self._claim_job(item=item)
            )
        except Exception:
            logger.exception("Job %s non leggibile, saltato", item.job_id)
            return False
        if claimed:
            self._active = item
        return claimed

    def _claim_job(self, item: WorkItem) -> bool:
        record = self._store.get(job_id=item.job_id)
        if action_status(record=record, item=item) != JobStatus.QUEUED:
            return False
        self._store.update(
            record=transition(record=record, item=item, status=JobStatus.RUNNING)
        )
        return True

    def _work(self) -> None:
        while (item := self._next_job()) is not None:
            try:
                self._execute(item=item)
            except Exception:
                logger.exception("Supervisione fallita per il job %s", item.job_id)
                with self._condition:
                    self._stop_process(graceful=False)
                    self._finish_failed(item=item, code="SUPERVISOR_ERROR")
            finally:
                with self._condition:
                    self._active = None

    def _finish_failed(self, item: WorkItem, code: str) -> None:
        if item.action == "generation":
            assert item.course_id is not None
            finish_generation(
                courses_dir=self._store.courses_dir,
                course_id=item.course_id,
                gen_id=item.job_id,
                status=GenerationStatus.FAILED,
                error=code,
            )
            return
        finish_action(store=self._store, item=item, status=JobStatus.FAILED, code=code)

    def _execute(self, item: WorkItem) -> None:
        if item.action == "generation":
            execute_generation_action(
                supervisor=self,
                item=item,
                ollama_unavailable_exit=OLLAMA_UNAVAILABLE_EXIT,
            )
            return
        if item.action == "pipeline":
            completed = execute_pipeline_action(supervisor=self, item=item)
        else:
            completed = self._run_stage(item=item, stage=JobStage.STUDY)
        if not completed:
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
            self._release_process(process=process)
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
