import logging
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sbobina.course_registry import find_by_key
from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.settings import settings
from sbobina.web import gpu_release
from sbobina.web.embedding_runner import estimate_embed_seconds
from sbobina.web.embedding_store import (
    EmbeddingRun,
    EmbeddingStatus,
    create_embed,
    load_embed,
    save_embed,
)
from sbobina.web.errors import ConflictError, JobNotCancellableError, NotFoundError
from sbobina.web.gpu_lock import LeaseCancelledError
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.processes import _spawn

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

logger = logging.getLogger(__name__)
EMBED_COMMAND = "embed"
EMBEDDING_STAGE = "embedding"
CHILD_LOG_NAME = "embedding_child.log"


def _require_course_id(store: JobStore, course_key: str) -> str:
    course = find_by_key(courses_dir=store.courses_dir, key=course_key)
    if course is None:
        raise NotFoundError(entity="Corso", id=course_key)
    return course.id


def _course_dir(store: JobStore, item: WorkItem) -> Path:
    assert item.course_id is not None
    return store.courses_dir / item.course_id


def submit_embed_item(
    store: JobStore, course_key: str
) -> tuple[EmbeddingRun, WorkItem]:
    course_id = _require_course_id(store=store, course_key=course_key)
    directory = store.courses_dir / course_id
    record = load_embed(course_dir=directory)
    if record is not None and record.status in (
        EmbeddingStatus.QUEUED,
        EmbeddingStatus.RUNNING,
    ):
        raise ConflictError(
            message="Indicizzazione semantica già in coda o in esecuzione",
            code="EMBED_ALREADY_QUEUED",
        )
    record = create_embed(course_dir=directory)
    return record, WorkItem(job_id=course_id, action="embed", course_id=course_id)


def cancel_embed_item(store: JobStore, course_key: str) -> WorkItem:
    course_id = _require_course_id(store=store, course_key=course_key)
    record = load_embed(course_dir=store.courses_dir / course_id)
    if record is None or record.status not in (
        EmbeddingStatus.QUEUED,
        EmbeddingStatus.RUNNING,
    ):
        raise JobNotCancellableError(job_id=course_id)
    return WorkItem(job_id=course_id, action="embed", course_id=course_id)


def mark_embed_interrupted(store: JobStore, item: WorkItem) -> None:
    directory = _course_dir(store=store, item=item)
    record = load_embed(course_dir=directory)
    if record is not None and record.status in (
        EmbeddingStatus.QUEUED,
        EmbeddingStatus.RUNNING,
    ):
        save_embed(
            course_dir=directory,
            record=replace(
                record,
                status=EmbeddingStatus.CANCELLED,
                error=None,
            ),
        )


def claim_embed_item(store: JobStore, item: WorkItem) -> bool:
    directory = _course_dir(store=store, item=item)
    record = load_embed(course_dir=directory)
    if record is None or record.status is not EmbeddingStatus.QUEUED:
        return False
    save_embed(
        course_dir=directory, record=replace(record, status=EmbeddingStatus.RUNNING)
    )
    return True


def _is_running(supervisor: "Supervisor", item: WorkItem) -> bool:
    record = load_embed(course_dir=_course_dir(store=supervisor._store, item=item))
    return (
        not supervisor._stopping
        and record is not None
        and record.status is EmbeddingStatus.RUNNING
    )


def launch_embed_process(
    supervisor: "Supervisor", item: WorkItem
) -> subprocess.Popen[bytes]:
    directory = _course_dir(store=supervisor._store, item=item)
    process = _spawn(
        command=[*supervisor._options.command, EMBED_COMMAND, str(directory)],
        log_path=directory / CHILD_LOG_NAME,
    )
    supervisor._process = process
    return process


def _run_embed_process(
    supervisor: "Supervisor",
    item: WorkItem,
    ollama_unavailable_exit: int,
) -> None:
    with supervisor._condition:
        if not _is_running(supervisor=supervisor, item=item):
            return
        process = launch_embed_process(supervisor=supervisor, item=item)
    return_code = process.wait()
    with supervisor._condition:
        supervisor._release_process(process=process)
        if return_code != 0:
            code = (
                "OLLAMA_UNAVAILABLE"
                if return_code == ollama_unavailable_exit
                else "STAGE_FAILED"
            )
            supervisor._finish_failed(item=item, code=code)


def _execute_with_lease(
    supervisor: "Supervisor",
    item: WorkItem,
    ollama_unavailable_exit: int,
    estimate: float,
) -> None:
    with supervisor._gpu_arbiter.transcription_lease(
        stage=EMBEDDING_STAGE,
        estimate_s=estimate,
        cancellation=supervisor._action_cancelled,
    ):
        try:
            gpu_release.unload_ollama_models(host=settings.ollama_host)
            _run_embed_process(
                supervisor=supervisor,
                item=item,
                ollama_unavailable_exit=ollama_unavailable_exit,
            )
        finally:
            gpu_release.unload_ollama_models(host=settings.ollama_host)


def execute_embed_action(
    supervisor: "Supervisor",
    item: WorkItem,
    ollama_unavailable_exit: int,
) -> None:
    directory = _course_dir(store=supervisor._store, item=item)
    try:
        estimate = estimate_embed_seconds(course_dir=directory)
        with supervisor._condition:
            if not _is_running(supervisor=supervisor, item=item):
                return
        _execute_with_lease(
            supervisor=supervisor,
            item=item,
            ollama_unavailable_exit=ollama_unavailable_exit,
            estimate=estimate,
        )
    except LeaseCancelledError:
        return
    except EmbeddingUnavailableError:
        logger.exception("Embedding model unavailable for course %s", item.course_id)
        with supervisor._condition:
            supervisor._finish_failed(item=item, code="OLLAMA_UNAVAILABLE")
