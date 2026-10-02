"""Single-slot background worker for document extraction (T014, D4).

One extraction runs at a time, in its own thread: the GPU transcription
queue (``Supervisor``) is untouched, and the FastAPI event loop keeps serving
requests while a child process parses a document.
"""

import logging
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Condition, Thread

from sbobina.document_models import CourseDocument, DocumentStatus
from sbobina.web.document_store import (
    document_dir,
    iter_extracting_documents,
    mark_extracted,
    mark_extracting,
    mark_failed,
    read_document,
    read_text,
    write_document,
)
from sbobina.web.errors import ConflictError
from sbobina.web.processes import _reap, _spawn

logger = logging.getLogger("sbobina")
DEFAULT_COMMAND = (sys.executable, "-m", "sbobina.web.extraction_runner")
CHILD_LOG_NAME = "extraction.log"
TERMINATE_TIMEOUT_S = 5.0
EXTRACT_SUBCOMMAND = "extract"


@dataclass(frozen=True)
class ExtractionWorkerOptions:
    command: tuple[str, ...] = DEFAULT_COMMAND
    timeout_s: float = 120.0
    max_memory_mb: int = 2048
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S


@dataclass(frozen=True)
class ExtractionItem:
    course_id: str
    doc_id: str


class ExtractionWorker:
    def __init__(
        self, courses_dir: Path, options: ExtractionWorkerOptions | None = None
    ) -> None:
        self._courses_dir = courses_dir
        self._options = options if options is not None else ExtractionWorkerOptions()
        self._condition = Condition()
        self._queue: deque[ExtractionItem] = deque()
        self._thread: Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stopping = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._condition:
            if self.is_running():
                return
            self._stopping = False
            self._thread = Thread(target=self._work, name="sbobina-extraction")
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
            process = self._process
        if process is not None:
            # Interrupted, not failed: the document stays ``extracting`` and
            # recover_on_boot re-queues it on the next start.
            _reap(
                process=process,
                timeout_s=self._options.terminate_timeout_s,
                graceful=False,
            )
        if thread is not None:
            thread.join()

    def recover_on_boot(self) -> None:
        """Re-queue documents a previous server run left in ``extracting``."""
        with self._condition:
            for document in iter_extracting_documents(courses_dir=self._courses_dir):
                item = ExtractionItem(course_id=document.course_id, doc_id=document.id)
                if item not in self._queue:
                    self._queue.append(item)

    def enqueue_new(self, document: CourseDocument) -> CourseDocument:
        """Persist a just-uploaded document as ``extracting`` and queue it.

        Writing and queueing under the worker lock leaves no on-disk state in
        which a concurrent delete could remove a document about to be extracted.
        """
        stored = replace(document, status=DocumentStatus.EXTRACTING)
        with self._condition:
            write_document(courses_dir=self._courses_dir, document=stored)
            self._queue.append(
                ExtractionItem(course_id=stored.course_id, doc_id=stored.id)
            )
            self._condition.notify()
        return stored

    def remove_if_idle(self, course_id: str, doc_id: str) -> None:
        """Delete a document's files unless its extraction is queued or running."""
        with self._condition:
            document = read_document(
                courses_dir=self._courses_dir, course_id=course_id, doc_id=doc_id
            )
            if document.status is DocumentStatus.EXTRACTING:
                raise ConflictError(
                    message="Documento in estrazione", code="DOCUMENT_BUSY"
                )
            shutil.rmtree(
                document_dir(
                    courses_dir=self._courses_dir, course_id=course_id, doc_id=doc_id
                )
            )

    def submit(self, course_id: str, doc_id: str) -> None:
        with self._condition:
            mark_extracting(
                courses_dir=self._courses_dir, course_id=course_id, doc_id=doc_id
            )
            self._queue.append(ExtractionItem(course_id=course_id, doc_id=doc_id))
            self._condition.notify()

    def _next_item(self) -> ExtractionItem | None:
        with self._condition:
            self._condition.wait_for(
                predicate=lambda: self._stopping or bool(self._queue)
            )
            if self._stopping:
                return None
            return self._queue.popleft()

    def _work(self) -> None:
        while (item := self._next_item()) is not None:
            try:
                self._run_one(item=item)
            except Exception:
                logger.exception(
                    "Estrazione fallita per %s/%s", item.course_id, item.doc_id
                )

    def _run_one(self, item: ExtractionItem) -> None:
        doc_dir = document_dir(
            courses_dir=self._courses_dir, course_id=item.course_id, doc_id=item.doc_id
        )
        return_code = self._run_child(item=item, doc_dir=doc_dir)
        if return_code is None or self._stopping:
            return  # timed out (already marked failed) or interrupted by stop
        if return_code != 0:
            mark_failed(
                courses_dir=self._courses_dir,
                course_id=item.course_id,
                doc_id=item.doc_id,
                code="EXTRACTION_FAILED",
            )
            return
        mark_extracted(
            courses_dir=self._courses_dir,
            course_id=item.course_id,
            doc_id=item.doc_id,
            result=read_text(doc_dir=doc_dir),
        )

    def _run_child(self, item: ExtractionItem, doc_dir: Path) -> int | None:
        process = _spawn(
            command=[
                *self._options.command,
                EXTRACT_SUBCOMMAND,
                str(doc_dir),
                str(self._options.max_memory_mb),
            ],
            log_path=doc_dir / CHILD_LOG_NAME,
        )
        # Visible to stop(), which terminates it instead of waiting the timeout.
        with self._condition:
            self._process = process
        try:
            return self._wait(item=item, process=process)
        finally:
            with self._condition:
                self._process = None

    def _wait(
        self, item: ExtractionItem, process: subprocess.Popen[bytes]
    ) -> int | None:
        try:
            return process.wait(timeout=self._options.timeout_s)
        except subprocess.TimeoutExpired:
            _reap(
                process=process,
                timeout_s=self._options.terminate_timeout_s,
                graceful=False,
            )
            mark_failed(
                courses_dir=self._courses_dir,
                course_id=item.course_id,
                doc_id=item.doc_id,
                code="EXTRACTION_TIMEOUT",
            )
            return None
        finally:
            if process.stdin is not None:
                process.stdin.close()
