import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_supervisor import Harness, harness, wait_for

from sbobina.course_registry import get_or_create
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.web import generation_supervisor, supervisor
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_store import (
    create_generation,
    generation_path,
    load_generation,
    save_generation,
)
from sbobina.web.job_models import WorkItem
from sbobina.web.processes import _spawn

__all__ = ["harness"]

REQUEST = GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=1)


def _register_course(harness: Harness, key: str = "fisica") -> str:
    course = get_or_create(
        courses_dir=harness.store.courses_dir, key=key, label="Fisica"
    )
    return course.id


def _status(harness: Harness, course_id: str, gen_id: str) -> GenerationStatus:
    record = load_generation(
        courses_dir=harness.store.courses_dir, course_id=course_id, gen_id=gen_id
    )
    return record.status


def _generation_marker(harness: Harness, course_id: str, name: str) -> Path:
    return harness.store.courses_dir / course_id / name


def test_submit_generation_rejects_unknown_course(harness: Harness) -> None:
    with pytest.raises(NotFoundError):
        harness.supervisor.submit_generation(course_key="sconosciuto", request=REQUEST)


def test_pipeline_then_generation_never_overlap_children(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fake runner doesn't write a GenerationRecord: on exit 0 the
    # supervisor leaves the status as the child would have left it (RUNNING,
    # since only the real child finalizes it); it never fakes a DONE itself.
    children: list[subprocess.Popen[bytes]] = []
    active_counts: list[int] = []

    def tracked_spawn(
        command: list[str], log_path: Path, untrusted: bool = False
    ) -> subprocess.Popen[bytes]:
        child = _spawn(command=command, log_path=log_path, untrusted=untrusted)
        children.append(child)
        active_counts.append(sum(p.poll() is None for p in children))
        return child

    monkeypatch.setattr(supervisor, "_spawn", tracked_spawn)
    monkeypatch.setattr(generation_supervisor, "_spawn", tracked_spawn)
    course_id = _register_course(harness=harness)
    job_id = harness.create(hold=True)
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)

    generation = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )
    assert _status(harness, course_id, generation.id) == GenerationStatus.QUEUED

    harness.marker(job_id=job_id, name="hold").unlink()
    wait_for(
        predicate=_generation_marker(
            harness=harness, course_id=course_id, name="generation.started"
        ).exists
    )
    wait_for(predicate=lambda: all(child.poll() is not None for child in children))

    assert active_counts == [1, 1]
    assert all(child.poll() == 0 for child in children)
    assert _status(harness, course_id, generation.id) == GenerationStatus.RUNNING


def test_recover_interrupts_running_generation_and_requeues_queued(
    harness: Harness,
) -> None:
    course_id = _register_course(harness=harness)
    running = create_generation(
        courses_dir=harness.store.courses_dir, course_id=course_id, request=REQUEST
    )
    queued = create_generation(
        courses_dir=harness.store.courses_dir, course_id=course_id, request=REQUEST
    )
    save_generation(
        courses_dir=harness.store.courses_dir,
        course_id=course_id,
        record=replace(running, status=GenerationStatus.RUNNING),
    )

    harness.supervisor.recover_on_boot()

    assert _status(harness, course_id, running.id) == GenerationStatus.INTERRUPTED
    assert (
        WorkItem(job_id=queued.id, action="generation", course_id=course_id)
        in harness.supervisor._queue
    )
    assert (
        WorkItem(job_id=running.id, action="generation", course_id=course_id)
        not in harness.supervisor._queue
    )


def test_queued_generation_runs_on_restart(harness: Harness) -> None:
    course_id = _register_course(harness=harness)
    generation = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )
    harness.supervisor.stop()

    harness.supervisor.start()

    wait_for(
        predicate=_generation_marker(
            harness=harness, course_id=course_id, name="generation.started"
        ).exists
    )
    wait_for(predicate=lambda: harness.supervisor._process is None)
    assert _status(harness, course_id, generation.id) == GenerationStatus.RUNNING


def test_cancel_queued_generation_then_resubmit(harness: Harness) -> None:
    course_id = _register_course(harness=harness)
    generation = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )

    harness.supervisor.cancel_generation(course_key="fisica", gen_id=generation.id)

    assert _status(harness, course_id, generation.id) == GenerationStatus.INTERRUPTED
    assert (
        WorkItem(job_id=generation.id, action="generation", course_id=course_id)
        not in harness.supervisor._queue
    )

    resubmitted = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )
    harness.supervisor.start()
    wait_for(
        predicate=_generation_marker(
            harness=harness, course_id=course_id, name="generation.started"
        ).exists
    )
    assert _status(harness, course_id, resubmitted.id) == GenerationStatus.RUNNING


def test_cancel_running_generation_kills_child_before_marking_interrupted(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _register_course(harness=harness)
    _generation_marker(harness=harness, course_id=course_id, name="hold").touch()
    generation = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )
    harness.supervisor.start()
    wait_for(
        predicate=_generation_marker(
            harness=harness, course_id=course_id, name="generation.started"
        ).exists
    )
    status_at_kill: list[GenerationStatus] = []
    original_stop = harness.supervisor._stop_process

    def recording_stop(graceful: bool) -> None:
        status_at_kill.append(_status(harness, course_id, generation.id))
        original_stop(graceful=graceful)

    monkeypatch.setattr(harness.supervisor, "_stop_process", recording_stop)

    harness.supervisor.cancel_generation(course_key="fisica", gen_id=generation.id)

    assert status_at_kill == [GenerationStatus.RUNNING]
    assert _status(harness, course_id, generation.id) == GenerationStatus.INTERRUPTED


def test_claim_generation_item_refuses_a_generation_already_claimed(
    harness: Harness,
) -> None:
    course_id = _register_course(harness=harness)
    queued = create_generation(
        courses_dir=harness.store.courses_dir, course_id=course_id, request=REQUEST
    )
    item = WorkItem(job_id=queued.id, action="generation", course_id=course_id)

    claims = [
        generation_supervisor.claim_generation_item(store=harness.store, item=item)
        for _ in range(2)
    ]

    assert claims == [True, False]
    assert _status(harness, course_id, queued.id) is GenerationStatus.RUNNING


def test_execute_generation_action_after_stop_launches_no_child(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _register_course(harness=harness)
    launched: list[WorkItem] = []
    monkeypatch.setattr(
        generation_supervisor,
        "launch_generation_process",
        lambda supervisor, item: launched.append(item),
    )
    harness.supervisor.stop()

    generation_supervisor.execute_generation_action(
        supervisor=harness.supervisor,
        item=WorkItem(job_id="g1", action="generation", course_id=course_id),
        ollama_unavailable_exit=2,
    )

    assert launched == []


def test_generation_corrupted_while_running_does_not_stop_the_queue(
    harness: Harness,
) -> None:
    # Both the run and its failure handler re-read the record: a corrupted
    # file must fail this item only, never kill the worker for every job.
    course_id = _register_course(harness=harness)
    _generation_marker(harness=harness, course_id=course_id, name="hold").touch()
    harness.supervisor.start()
    generation = harness.supervisor.submit_generation(
        course_key="fisica", request=REQUEST
    )
    wait_for(
        predicate=_generation_marker(
            harness=harness, course_id=course_id, name="generation.started"
        ).exists
    )
    generation_path(
        courses_dir=harness.store.courses_dir,
        course_id=course_id,
        gen_id=generation.id,
    ).write_text("{broken", encoding="utf-8")
    (harness.store.courses_dir / course_id / "generation.exit").write_text("1")
    kept = harness.create()
    harness.supervisor.submit(job_id=kept)

    _generation_marker(harness=harness, course_id=course_id, name="hold").unlink()

    wait_for(predicate=lambda: harness.finished(job_id=kept))
    assert harness.supervisor.is_running()
