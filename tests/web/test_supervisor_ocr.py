import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from ocr_fixtures import COURSE_KEY, DOC_ID, add_scanned_document
from test_supervisor import Harness, harness, wait_for

from sbobina.document_models import DocumentStatus
from sbobina.settings import settings
from sbobina.web import ocr_supervisor, supervisor
from sbobina.web.errors import (
    ConflictError,
    JobNotCancellableError,
    NotFoundError,
)
from sbobina.web.job_models import WorkItem
from sbobina.web.ocr_store import OcrStatus, create_ocr, load_ocr, save_ocr
from sbobina.web.processes import _spawn

__all__ = ["harness"]


def _status(harness: Harness, course_id: str) -> OcrStatus:
    run = load_ocr(
        courses_dir=harness.store.courses_dir, course_id=course_id, doc_id=DOC_ID
    )
    assert run is not None
    return run.status


def test_submit_rejects_a_document_that_already_has_text(harness: Harness) -> None:
    add_scanned_document(
        courses_dir=harness.store.courses_dir, status=DocumentStatus.READY
    )

    with pytest.raises(ConflictError) as error:
        harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    assert error.value.code == "OCR_NOT_ELIGIBLE"


def test_second_submit_while_queued_is_rejected(harness: Harness) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    with pytest.raises(ConflictError) as error:
        harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    assert error.value.code == "OCR_ALREADY_QUEUED"
    assert _status(harness=harness, course_id=course_id) is OcrStatus.QUEUED


def test_cancel_queued_ocr_removes_it_from_the_queue(harness: Harness) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    harness.supervisor.cancel_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    assert _status(harness=harness, course_id=course_id) is OcrStatus.INTERRUPTED
    item = WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id)
    assert item not in harness.supervisor._queue


def test_cancel_running_ocr_kills_the_child_before_marking_it(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=harness.store.courses_dir)
    (doc_dir / "hold").touch()
    harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)
    harness.supervisor.start()
    wait_for(predicate=(doc_dir / "ocr.started").exists)
    seen: list[OcrStatus] = []
    original_stop = harness.supervisor._stop_process

    def recording_stop(graceful: bool) -> None:
        seen.append(_status(harness=harness, course_id=course_id))
        original_stop(graceful=graceful)

    monkeypatch.setattr(harness.supervisor, "_stop_process", recording_stop)

    harness.supervisor.cancel_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    assert seen == [OcrStatus.RUNNING]
    assert _status(harness=harness, course_id=course_id) is OcrStatus.INTERRUPTED


def test_recover_interrupts_running_ocr_and_requeues_queued(harness: Harness) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    run = create_ocr(
        courses_dir=harness.store.courses_dir, course_id=course_id, doc_id=DOC_ID
    )
    save_ocr(
        courses_dir=harness.store.courses_dir,
        course_id=course_id,
        doc_id=DOC_ID,
        record=replace(run, status=OcrStatus.RUNNING),
    )

    harness.supervisor.recover_on_boot()

    assert _status(harness=harness, course_id=course_id) is OcrStatus.INTERRUPTED
    item = WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id)
    assert item not in harness.supervisor._queue


def test_pipeline_then_ocr_never_overlap_children(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(ocr_supervisor, "_spawn", tracked_spawn)
    _, doc_dir = add_scanned_document(courses_dir=harness.store.courses_dir)
    job_id = harness.create(hold=True)
    harness.supervisor.start()
    wait_for(predicate=harness.marker(job_id=job_id, name="transcribe.started").exists)

    harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)
    harness.marker(job_id=job_id, name="hold").unlink()
    wait_for(predicate=(doc_dir / "ocr.started").exists)
    wait_for(predicate=lambda: all(child.poll() is not None for child in children))

    assert active_counts == [1, 1]


def test_ocr_process_timeout_kills_the_child_and_marks_the_run_failed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=harness.store.courses_dir)
    (doc_dir / "hold").touch()
    monkeypatch.setattr(settings, "ocr_process_timeout_s", 0.05)
    second_job_id = harness.create()
    harness.supervisor.submit_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)
    harness.supervisor.submit(job_id=second_job_id)
    harness.supervisor.start()

    wait_for(
        predicate=lambda: (
            _status(harness=harness, course_id=course_id) is OcrStatus.FAILED
        )
    )

    run = load_ocr(
        courses_dir=harness.store.courses_dir, course_id=course_id, doc_id=DOC_ID
    )
    assert run is not None
    assert run.error == "OCR_TIMEOUT"
    wait_for(predicate=lambda: harness.finished(job_id=second_job_id))


def test_recover_keeps_a_run_whose_text_was_already_written(harness: Harness) -> None:
    # Crash between writing text.json/document.json and marking the run done:
    # the document is READY, so the run succeeded and must not read as stopped.
    course_id, _ = add_scanned_document(
        courses_dir=harness.store.courses_dir, status=DocumentStatus.READY
    )
    run = create_ocr(
        courses_dir=harness.store.courses_dir, course_id=course_id, doc_id=DOC_ID
    )
    save_ocr(
        courses_dir=harness.store.courses_dir,
        course_id=course_id,
        doc_id=DOC_ID,
        record=replace(run, status=OcrStatus.RUNNING),
    )

    harness.supervisor.recover_on_boot()

    assert _status(harness=harness, course_id=course_id) is OcrStatus.DONE


def _save_run(harness: Harness, course_id: str, status: OcrStatus) -> None:
    run = create_ocr(
        courses_dir=harness.store.courses_dir, course_id=course_id, doc_id=DOC_ID
    )
    save_ocr(
        courses_dir=harness.store.courses_dir,
        course_id=course_id,
        doc_id=DOC_ID,
        record=replace(
            run,
            status=status,
            error="OCR_FAILED" if status is OcrStatus.FAILED else None,
        ),
    )


def test_submit_ocr_unknown_course_is_not_found(harness: Harness) -> None:
    with pytest.raises(NotFoundError):
        harness.supervisor.submit_ocr(course_key="sconosciuto", doc_id=DOC_ID)


def test_recover_interrupts_running_ocr_whose_document_is_unreadable(
    harness: Harness,
) -> None:
    course_id, doc_dir = add_scanned_document(courses_dir=harness.store.courses_dir)
    _save_run(harness=harness, course_id=course_id, status=OcrStatus.RUNNING)
    (doc_dir / "document.json").write_text("{", encoding="utf-8")

    harness.supervisor.recover_on_boot()

    assert _status(harness=harness, course_id=course_id) is OcrStatus.INTERRUPTED


@pytest.mark.parametrize("status", [OcrStatus.DONE, OcrStatus.FAILED])
def test_recover_leaves_finished_ocr_runs_untouched_and_unqueued(
    harness: Harness, status: OcrStatus
) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    _save_run(harness=harness, course_id=course_id, status=status)

    harness.supervisor.recover_on_boot()

    item = WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id)
    assert (
        _status(harness=harness, course_id=course_id),
        item in harness.supervisor._queue,
    ) == (status, False)


def test_cancel_ocr_without_a_pending_run_is_not_cancellable(harness: Harness) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    _save_run(harness=harness, course_id=course_id, status=OcrStatus.DONE)

    with pytest.raises(JobNotCancellableError):
        harness.supervisor.cancel_ocr(course_key=COURSE_KEY, doc_id=DOC_ID)

    assert _status(harness=harness, course_id=course_id) is OcrStatus.DONE


def test_claim_ocr_item_refuses_a_run_already_claimed(harness: Harness) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    _save_run(harness=harness, course_id=course_id, status=OcrStatus.QUEUED)
    item = WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id)

    claims = [
        ocr_supervisor.claim_ocr_item(store=harness.store, item=item) for _ in range(2)
    ]

    assert claims == [True, False]
    assert _status(harness=harness, course_id=course_id) is OcrStatus.RUNNING


def test_execute_ocr_action_after_stop_launches_no_child(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id, _ = add_scanned_document(courses_dir=harness.store.courses_dir)
    launched: list[WorkItem] = []
    monkeypatch.setattr(
        ocr_supervisor,
        "launch_ocr_process",
        lambda supervisor, item: launched.append(item),
    )
    harness.supervisor.stop()

    ocr_supervisor.execute_ocr_action(
        supervisor=harness.supervisor,
        item=WorkItem(job_id=DOC_ID, action="ocr", course_id=course_id),
        ollama_unavailable_exit=2,
    )

    assert launched == []
