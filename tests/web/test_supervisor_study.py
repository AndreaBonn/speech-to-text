import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_supervisor import Harness, harness, wait_for

from sbobina.web import supervisor
from sbobina.web.errors import ConflictError
from sbobina.web.job_models import JobStatus, StudyRun, StudyStatus, WorkItem
from sbobina.web.processes import _spawn

__all__ = ["harness"]


def done_job(harness: Harness, hold: bool = False) -> str:
    job_id = harness.create(hold=hold)
    harness.store.update(
        record=harness.record(job_id=job_id).model_copy(
            update={"status": JobStatus.DONE}
        )
    )
    harness.marker(job_id=job_id, name="audio.json").write_text("{}")
    return job_id


def study_status(harness: Harness, job_id: str) -> StudyStatus | None:
    study = harness.record(job_id=job_id).study
    return study.status if study is not None else None


def test_legacy_job_json_without_study_loads(harness: Harness) -> None:
    job_id = harness.create()
    record = harness.record(job_id=job_id)
    harness.marker(job_id=job_id, name="job.json").write_text(
        record.model_dump_json(exclude={"study"})
    )
    loaded = harness.record(job_id=job_id)
    assert loaded.id == record.id
    assert loaded.study is None


def test_pipeline_then_study_never_overlap_children(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    children: list[subprocess.Popen[bytes]] = []
    active_counts: list[int] = []

    def tracked_spawn(command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
        child = _spawn(command=command, log_path=log_path)
        children.append(child)
        active_counts.append(sum(p.poll() is None for p in children))
        return child

    monkeypatch.setattr(supervisor, "_spawn", tracked_spawn)
    first = harness.create(correct=True, hold=True)
    second = done_job(harness=harness)
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=first, name="transcribe.started").exists)
    harness.supervisor.submit_study(job_id=second)
    assert study_status(harness=harness, job_id=second) == StudyStatus.QUEUED
    harness.marker(job_id=first, name="hold").unlink()
    wait_for(predicate=lambda: study_status(harness, second) == StudyStatus.DONE)
    assert active_counts == [1, 1, 1]
    assert all(child.poll() == 0 for child in children)
    assert harness.record(job_id=second).status == JobStatus.DONE
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{first}:transcribe",
        f"{first}:correct",
        f"{second}:study",
    ]


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_submit_study_rejects_unfinished_job(
    harness: Harness, status: JobStatus
) -> None:
    job_id = harness.create()
    harness.store.update(
        record=harness.record(job_id).model_copy(update={"status": status})
    )
    with pytest.raises(ConflictError):
        harness.supervisor.submit_study(job_id=job_id)
    assert harness.record(job_id).status == status
    assert harness.record(job_id).study is None


def test_submit_study_requires_transcript(harness: Harness) -> None:
    job_id = done_job(harness=harness)
    harness.marker(job_id=job_id, name="audio.json").unlink()
    with pytest.raises(ConflictError):
        harness.supervisor.submit_study(job_id=job_id)
    assert harness.record(job_id).status == JobStatus.DONE
    assert harness.record(job_id).study is None


def test_recover_studies_interrupts_running_and_merges_fifo(harness: Harness) -> None:
    old = done_job(harness=harness)
    running = done_job(harness=harness)
    pipeline = harness.create()
    now = datetime.now(tz=UTC)
    for job_id, status, updated in [
        (running, StudyStatus.RUNNING, now - timedelta(seconds=1)),
        (old, StudyStatus.QUEUED, now),
    ]:
        harness.store.update(
            record=harness.record(job_id).model_copy(
                update={
                    "study": StudyRun(status=status, updated_at=updated),
                    "pid": 12345,
                }
            )
        )
    harness.supervisor.start()
    wait_for(predicate=lambda: study_status(harness, old) == StudyStatus.DONE)
    record = harness.record(running)
    assert record.status == JobStatus.DONE and record.pid is None
    assert record.study is not None
    assert record.study.status == StudyStatus.INTERRUPTED
    assert record.study.error == {"code": "SERVER_RESTARTED"}
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{pipeline}:transcribe",
        f"{old}:study",
    ]


@pytest.mark.parametrize("action", ["cancel", "stop"])
def test_running_study_interruption_reaps_child(harness: Harness, action: str) -> None:
    job_id = done_job(harness=harness, hold=True)
    harness.supervisor.submit_study(job_id=job_id)
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=job_id, name="study.started").exists)
    child = harness.supervisor._process
    assert child is not None
    if action == "cancel":
        harness.supervisor.cancel(job_id=job_id)
    else:
        harness.supervisor.stop()
    assert child.poll() is not None
    assert study_status(harness, job_id) == StudyStatus.INTERRUPTED
    record = harness.record(job_id)
    assert record.status == JobStatus.DONE and record.pid is None


def test_cancel_queued_study_and_resubmit(harness: Harness) -> None:
    job_id = done_job(harness=harness)
    harness.supervisor.submit_study(job_id=job_id)
    harness.supervisor.cancel(job_id=job_id)
    assert study_status(harness, job_id) == StudyStatus.INTERRUPTED
    harness.supervisor.submit_study(job_id=job_id)
    harness.supervisor.start()
    wait_for(predicate=lambda: study_status(harness, job_id) == StudyStatus.DONE)
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{job_id}:study"
    ]


def test_study_unavailable_preserves_material_and_continues_queue(
    harness: Harness,
) -> None:
    job_id = done_job(harness=harness)
    harness.marker(job_id=job_id, name="study.exit").write_text("2")
    material = harness.marker(job_id=job_id, name="audio.studio.md")
    material.write_text("previous material")
    harness.supervisor.submit_study(job_id=job_id)
    next_job = harness.create()
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.finished(job_id=next_job))
    record = harness.record(job_id)
    assert record.study is not None and record.study.status == StudyStatus.FAILED
    assert record.study.error == {"code": "OLLAMA_UNAVAILABLE"}
    assert record.status == JobStatus.DONE and record.error is None
    assert material.read_text() == "previous material"


def test_work_item_is_typed_and_frozen() -> None:
    item = WorkItem(job_id="job", action="study")
    assert item.action == "study" and item.job_id == "job"
    with pytest.raises(ValueError):
        WorkItem.model_validate({"job_id": "job", "action": "other"})
    with pytest.raises(ValueError):
        item.action = "pipeline"


def test_cancel_running_study_then_resubmit_is_not_overwritten(
    harness: Harness,
) -> None:
    job_id = done_job(harness=harness, hold=True)
    harness.supervisor.start()
    harness.supervisor.submit_study(job_id=job_id)
    wait_for(predicate=harness.marker(job_id=job_id, name="study.started").exists)
    previous = harness.supervisor._process
    assert previous is not None
    with harness.supervisor._condition:
        harness.supervisor.cancel(job_id=job_id)
        harness.marker(job_id=job_id, name="hold").unlink()
        harness.supervisor.submit_study(job_id=job_id)
    wait_for(predicate=lambda: study_status(harness, job_id) == StudyStatus.DONE)
    assert previous.poll() is not None
    assert harness.record(job_id).status == JobStatus.DONE
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{job_id}:study",
        f"{job_id}:study",
    ]


def test_queued_studies_restart_in_submission_order(harness: Harness) -> None:
    first_created = done_job(harness=harness)
    second_created = done_job(harness=harness)
    corrected = harness.marker(job_id=second_created, name="audio.corretto.json")
    harness.marker(job_id=second_created, name="audio.json").rename(corrected)
    harness.supervisor.submit_study(job_id=second_created)
    harness.supervisor.submit_study(job_id=first_created)
    harness.supervisor.stop()
    harness.supervisor.start()
    wait_for(predicate=lambda: study_status(harness, first_created) == StudyStatus.DONE)
    assert (harness.store.jobs_dir / "order.log").read_text().splitlines() == [
        f"{second_created}:study",
        f"{first_created}:study",
    ]


@pytest.mark.parametrize("status", [StudyStatus.QUEUED, StudyStatus.RUNNING])
def test_submit_study_rejects_duplicate_action(
    harness: Harness, status: StudyStatus
) -> None:
    job_id = done_job(harness=harness)
    study = StudyRun(status=status, updated_at=datetime.now(tz=UTC))
    harness.store.update(
        record=harness.record(job_id).model_copy(update={"study": study})
    )
    with pytest.raises(ConflictError) as caught:
        harness.supervisor.submit_study(job_id=job_id)
    assert caught.value.code == "STUDY_ALREADY_QUEUED"
    assert harness.record(job_id).study == study
