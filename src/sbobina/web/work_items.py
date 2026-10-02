import logging
from collections import deque
from datetime import UTC, datetime

from pydantic import JsonValue

from sbobina.study_command import select_study_paths
from sbobina.web.errors import ConflictError, JobNotCancellableError, NotFoundError
from sbobina.web.job_models import (
    JobRecord,
    JobStage,
    JobStatus,
    StudyRun,
    StudyStatus,
    WorkItem,
)
from sbobina.web.job_store import JobStore


def action_status(record: JobRecord, item: WorkItem) -> str | None:
    if item.action == "study":
        return record.study.status if record.study is not None else None
    return record.status


def transition(
    record: JobRecord, item: WorkItem, status: JobStatus, code: str | None = None
) -> JobRecord:
    error: dict[str, JsonValue] | None = {"code": code} if code is not None else None
    if item.action == "study":
        return record.model_copy(
            update={
                "study": StudyRun(
                    status=StudyStatus(status),
                    error=error,
                    updated_at=datetime.now(tz=UTC),
                ),
                "pid": None,
            }
        )
    update: dict[str, object] = {"status": status, "error": error, "pid": None}
    if status == JobStatus.DONE:
        update["stage"] = JobStage.DONE
    return record.model_copy(update=update)


def prepare_study(store: JobStore, job_id: str) -> JobRecord:
    record = store.get(job_id=job_id)
    path = select_study_paths(
        path=store.jobs_dir / str(record.id) / "audio.json"
    ).source
    if record.status != JobStatus.DONE or not path.is_file():
        raise ConflictError(
            message="Il job non ha una trascrizione pronta", code="STUDY_NOT_READY"
        )
    if record.study is not None and record.study.status in (
        StudyStatus.QUEUED,
        StudyStatus.RUNNING,
    ):
        raise ConflictError(
            message="Studio già in coda o in esecuzione", code="STUDY_ALREADY_QUEUED"
        )
    return record


def recover_record(
    store: JobStore, record: JobRecord
) -> list[tuple[datetime, WorkItem]]:
    queued = []
    for action in ("pipeline", "study"):
        item = WorkItem(job_id=str(record.id), action=action)
        status = action_status(record=record, item=item)
        if status == JobStatus.RUNNING:
            record = store.update(
                record=transition(
                    record=record,
                    item=item,
                    status=JobStatus.INTERRUPTED,
                    code="SERVER_RESTARTED",
                )
            )
        elif status == JobStatus.QUEUED:
            timestamp = (
                record.study.updated_at
                if action == "study" and record.study
                else record.created_at
            )
            queued.append((timestamp, item))
    return queued


def recover_queue(store: JobStore, page_size: int) -> deque[WorkItem]:
    page = store.list(page=1, per_page=page_size)
    records = list(page.items)
    for number in range(2, page.total_pages + 1):
        records.extend(store.list(page=number, per_page=page_size).items)
    queued = [
        entry
        for record in records
        for entry in recover_record(store=store, record=record)
    ]
    return deque(item for _, item in sorted(queued, key=lambda entry: entry[0]))


def cancel_action(record: JobRecord) -> tuple[WorkItem, JobStatus]:
    item = WorkItem(
        job_id=str(record.id),
        action="study" if record.status == JobStatus.DONE else "pipeline",
    )
    if action_status(record=record, item=item) not in (
        JobStatus.QUEUED,
        JobStatus.RUNNING,
    ):
        raise JobNotCancellableError(job_id=item.job_id)
    status = JobStatus.INTERRUPTED if item.action == "study" else JobStatus.CANCELLED
    return item, status


def finish_action(
    store: JobStore, item: WorkItem, status: JobStatus, code: str | None = None
) -> None:
    try:
        record = store.get(job_id=item.job_id)
    except NotFoundError:
        logging.getLogger("sbobina").warning(
            "Job %s rimosso dal disco durante l'esecuzione", item.job_id
        )
        return
    if action_status(record=record, item=item) == JobStatus.RUNNING:
        store.update(
            record=transition(record=record, item=item, status=status, code=code)
        )
