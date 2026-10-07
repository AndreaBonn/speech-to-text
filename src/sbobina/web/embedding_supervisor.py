import logging
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sbobina import ollama_embed
from sbobina.course_registry import find_by_key, get_or_create
from sbobina.courses import MAX_COURSE_LABEL_LENGTH, course_key, effective_course
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
from sbobina.web.job_models import JobRecord, JobStatus, WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.processes import _spawn
from sbobina.web.work_items import action_status

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

logger = logging.getLogger(__name__)
EMBED_COMMAND = "embed"
EMBEDDING_STAGE = "embedding"
CHILD_LOG_NAME = "embedding_child.log"
# Enqueue probes run on serial queue workers: a hung Ollama must not stall them
# for the full embedding timeout. A refused local connection fails at once anyway.
ENQUEUE_PROBE_TIMEOUT_S = 2.0


def _require_course_id(store: JobStore, course_key: str) -> str:
    course = find_by_key(courses_dir=store.courses_dir, key=course_key)
    if course is None:
        raise NotFoundError(entity="Corso", id=course_key)
    return course.id


def _course_dir(store: JobStore, item: WorkItem) -> Path:
    assert item.course_id is not None
    return store.courses_dir / item.course_id


def submit_embed_item(
    store: JobStore, course_key: str = "", *, course_id: str | None = None
) -> tuple[EmbeddingRun, WorkItem]:
    if course_id is None:
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


def _lecture_course_id(store: JobStore, record: JobRecord) -> str | None:
    meta = store.read_meta(job_id=str(record.id))
    label = effective_course(course=meta.course, subject=record.config.subject)
    if label is None:
        return None
    if len(label) > MAX_COURSE_LABEL_LENGTH:
        logger.warning("Course label exceeds registry limit for job %s", record.id)
        return None
    return get_or_create(
        courses_dir=store.courses_dir, key=course_key(label=label), label=label
    ).id


def _embedding_unavailable_reason() -> str | None:
    try:
        ollama_embed.model_status(
            host=settings.ollama_host,
            model=settings.embedding_model,
            timeout_s=ENQUEUE_PROBE_TIMEOUT_S,
        )
    except EmbeddingUnavailableError as error:
        logger.warning("Automatic embedding unavailable: %s", error.reason)
        return error.reason
    return None


def _enqueue_checked_embed(
    supervisor: "Supervisor", course_id: str, reason: str | None
) -> None:
    directory = supervisor._store.courses_dir / course_id
    record = load_embed(course_dir=directory)
    if record is not None and record.status in (
        EmbeddingStatus.QUEUED,
        EmbeddingStatus.RUNNING,
    ):
        return
    if reason is not None:
        save_embed(
            course_dir=directory,
            record=EmbeddingRun(
                status=EmbeddingStatus.FAILED, processed=0, total=0, error=reason
            ),
        )
        return
    try:
        _, item = submit_embed_item(store=supervisor._store, course_id=course_id)
    except ConflictError as error:
        if error.code != "EMBED_ALREADY_QUEUED":
            raise
        return
    supervisor._queue.append(item)
    supervisor._condition.notify()


def maybe_enqueue_embed(
    supervisor: "Supervisor",
    course_id: str | None = None,
    record: JobRecord | None = None,
    item: WorkItem | None = None,
) -> None:
    """Queue one course after a text change; log failures, the change itself stands."""
    try:
        _enqueue_after_change(
            supervisor=supervisor, course_id=course_id, record=record, item=item
        )
    except Exception:
        logger.exception(
            "Automatic embedding enqueue failed (course %s, job %s)",
            course_id,
            getattr(item, "job_id", None) or getattr(record, "id", None),
        )


def _enqueue_after_change(
    supervisor: "Supervisor",
    course_id: str | None,
    record: JobRecord | None,
    item: WorkItem | None,
) -> None:
    if not settings.semantic_search:
        return
    if item is not None:
        record = supervisor._store.get(job_id=item.job_id)
        if action_status(record=record, item=item) != JobStatus.DONE:
            return
    if course_id is None and record is not None:
        course_id = _lecture_course_id(store=supervisor._store, record=record)
    if course_id is None:
        return
    reason = _embedding_unavailable_reason()
    with supervisor._condition:
        _enqueue_checked_embed(
            supervisor=supervisor, course_id=course_id, reason=reason
        )


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
            detail = (
                f"exit={return_code}" if return_code > 0 else f"signal={-return_code}"
            )
            code = (
                "OLLAMA_UNAVAILABLE"
                if return_code == ollama_unavailable_exit
                else f"STAGE_FAILED ({detail})"
            )
            logger.error(
                "Embedding child failed for course %s: %s", item.course_id, code
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
