"""Supervisor-side helpers for the "generation" action.

Factored out of supervisor.py to stay under the file size limit. The queue
helpers (submit/cancel/claim) only need a JobStore. execute/launch need the
supervisor's own lock and process slot, so they take the Supervisor instance
itself (TYPE_CHECKING-only import avoids the circular import, since
supervisor.py imports this module at runtime): same trust boundary as a
Supervisor method, just kept in a second file.
"""

import subprocess
from typing import TYPE_CHECKING

from sbobina.course_registry import find_by_key
from sbobina.generation_models import (
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_queue import (
    cancel_generation_action,
    require_cancellable,
    transition_generation,
)
from sbobina.web.generation_store import (
    create_generation,
    load_generation,
    save_generation,
)
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.processes import _spawn

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

GENERATION_COMMAND = "generation"
CHILD_LOG_NAME = "child.log"


def _require_course_id(store: JobStore, course_key: str) -> str:
    course = find_by_key(courses_dir=store.courses_dir, key=course_key)
    if course is None:
        raise NotFoundError(entity="Corso", id=course_key)
    return course.id


def submit_generation_item(
    store: JobStore, course_key: str, request: GenerationRequest
) -> tuple[GenerationRecord, WorkItem]:
    course_id = _require_course_id(store=store, course_key=course_key)
    record = create_generation(
        courses_dir=store.courses_dir, course_id=course_id, request=request
    )
    item = WorkItem(job_id=record.id, action="generation", course_id=course_id)
    return record, item


def cancel_generation_item(store: JobStore, course_key: str, gen_id: str) -> WorkItem:
    """The queue item of a cancellable generation; writes nothing yet."""
    course_id = _require_course_id(store=store, course_key=course_key)
    require_cancellable(
        courses_dir=store.courses_dir, course_id=course_id, gen_id=gen_id
    )
    return WorkItem(job_id=gen_id, action="generation", course_id=course_id)


def mark_generation_interrupted(store: JobStore, item: WorkItem) -> None:
    """Called after the child is killed, so it cannot overwrite INTERRUPTED."""
    assert item.course_id is not None
    cancel_generation_action(
        courses_dir=store.courses_dir, course_id=item.course_id, gen_id=item.job_id
    )


def claim_generation_item(store: JobStore, item: WorkItem) -> bool:
    """True once this generation is marked RUNNING; False if already claimed."""
    assert item.course_id is not None
    record = load_generation(
        courses_dir=store.courses_dir, course_id=item.course_id, gen_id=item.job_id
    )
    if record.status != GenerationStatus.QUEUED:
        return False
    save_generation(
        courses_dir=store.courses_dir,
        course_id=item.course_id,
        record=transition_generation(record=record, status=GenerationStatus.RUNNING),
    )
    return True


def launch_generation_process(
    supervisor: "Supervisor", item: WorkItem
) -> subprocess.Popen[bytes]:
    assert item.course_id is not None
    directory = supervisor._store.courses_dir / item.course_id
    process = _spawn(
        command=[*supervisor._options.command, GENERATION_COMMAND, str(directory)],
        log_path=directory / CHILD_LOG_NAME,
    )
    supervisor._process = process
    return process


def execute_generation_action(
    supervisor: "Supervisor", item: WorkItem, ollama_unavailable_exit: int
) -> None:
    """The child persists its own DONE record on success (unlike study,
    there is no separate status for the supervisor to set here)."""
    with supervisor._condition:
        if supervisor._stopping:
            return
        process = launch_generation_process(supervisor=supervisor, item=item)
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
