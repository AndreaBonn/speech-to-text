from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness
from test_supervisor import wait_for

from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.web import course_actions, embedding_supervisor
from sbobina.web.embedding_store import (
    EmbeddingRun,
    EmbeddingStatus,
    create_embed,
    save_embed,
)
from sbobina.web.errors import ConflictError, JobNotCancellableError, NotFoundError
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore

__all__ = ["embedding_harness"]


def test_enqueue_checked_embed_submit_race_keeps_one_item(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    course_id = harness.course_dir.name
    real_submit = embedding_supervisor.submit_embed_item

    def competing_submit(
        *, store: JobStore, course_id: str
    ) -> tuple[EmbeddingRun, WorkItem]:
        _, competing = real_submit(store=store, course_id=course_id)
        harness.supervisor._queue.append(competing)
        return real_submit(store=store, course_id=course_id)

    monkeypatch.setattr(embedding_supervisor, "submit_embed_item", competing_submit)
    with harness.supervisor._condition:
        embedding_supervisor._enqueue_checked_embed(
            supervisor=harness.supervisor, course_id=course_id, reason=None
        )

    assert list(harness.supervisor._queue) == [
        WorkItem(job_id=course_id, course_id=course_id, action="embed")
    ]
    assert harness.record().status is EmbeddingStatus.QUEUED


def test_enqueue_checked_embed_unexpected_conflict_is_reraised(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    conflict = ConflictError(message="Storage conflict", code="STORAGE_CONFLICT")

    def conflict_on_submit(
        *, store: JobStore, course_id: str
    ) -> tuple[EmbeddingRun, WorkItem]:
        raise conflict

    with monkeypatch.context() as patch:
        patch.setattr(embedding_supervisor, "submit_embed_item", conflict_on_submit)
        with harness.supervisor._condition, pytest.raises(ConflictError) as caught:
            embedding_supervisor._enqueue_checked_embed(
                supervisor=harness.supervisor,
                course_id=harness.course_dir.name,
                reason=None,
            )

    assert caught.value is conflict
    assert list(harness.supervisor._queue) == []
    with harness.supervisor._condition:
        embedding_supervisor._enqueue_checked_embed(
            supervisor=harness.supervisor,
            course_id=harness.course_dir.name,
            reason=None,
        )
    assert list(harness.supervisor._queue) == [
        WorkItem(
            job_id=harness.course_dir.name,
            course_id=harness.course_dir.name,
            action="embed",
        )
    ]


def test_execute_embed_action_cancelled_during_estimate_skips_lease_and_child(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = embedding_harness
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    item = harness.supervisor._queue.popleft()
    assert embedding_supervisor.claim_embed_item(store=harness.store, item=item)

    def cancel_during_estimate(*, course_dir: Path) -> float:
        save_embed(
            course_dir=course_dir,
            record=replace(harness.record(), status=EmbeddingStatus.CANCELLED),
        )
        return 10.0

    with monkeypatch.context() as patch:
        patch.setattr(
            embedding_supervisor, "estimate_embed_seconds", cancel_during_estimate
        )
        embedding_supervisor.execute_embed_action(
            supervisor=harness.supervisor, item=item, ollama_unavailable_exit=2
        )

    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert harness.released == []
    assert not (harness.course_dir / "embed.started").exists()

    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    retry = harness.supervisor._queue.popleft()
    assert embedding_supervisor.claim_embed_item(store=harness.store, item=retry)
    embedding_supervisor.execute_embed_action(
        supervisor=harness.supervisor, item=retry, ollama_unavailable_exit=2
    )
    assert harness.record().status is EmbeddingStatus.DONE
    assert (harness.course_dir / "embed.started").exists()
    assert harness.released == [("chat:9b", 0), ("test", 0)]


def test_duplicate_submits_queue_one_course(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness

    def submit() -> str:
        try:
            course_actions.submit_embed(
                supervisor=harness.supervisor, course_key="diritto"
            )
            return "queued"
        except ConflictError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(results) == ["EMBED_ALREADY_QUEUED", "queued"]
    assert len(harness.supervisor._queue) == 1
    assert harness.record().status is EmbeddingStatus.QUEUED


def test_cancel_queued_removes_item_and_allows_resubmit(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    assert len(harness.supervisor._queue) == 1
    course_actions.cancel_embed(supervisor=harness.supervisor, course_key="diritto")
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert list(harness.supervisor._queue) == []
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    assert len(harness.supervisor._queue) == 1


def test_submit_unknown_course_and_cancel_without_run(
    embedding_harness: EmbeddingHarness,
) -> None:
    supervisor = embedding_harness.supervisor
    with pytest.raises(NotFoundError):
        course_actions.submit_embed(supervisor=supervisor, course_key="missing")
    with pytest.raises(JobNotCancellableError):
        course_actions.cancel_embed(supervisor=supervisor, course_key="diritto")


def test_claim_only_once_and_recover_running_as_cancelled(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    item = harness.supervisor._queue[0]
    assert embedding_supervisor.claim_embed_item(store=harness.store, item=item)
    assert not embedding_supervisor.claim_embed_item(store=harness.store, item=item)
    harness.supervisor.recover_on_boot()
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert list(harness.supervisor._queue) == []


def test_recover_queued_and_preserve_terminal(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness
    record = create_embed(course_dir=harness.course_dir)
    harness.supervisor.recover_on_boot()
    assert list(harness.supervisor._queue) == [
        WorkItem(
            job_id=harness.course_dir.name,
            course_id=harness.course_dir.name,
            action="embed",
        )
    ]
    save_embed(
        course_dir=harness.course_dir,
        record=replace(record, status=EmbeddingStatus.DONE),
    )
    harness.supervisor.recover_on_boot()
    assert list(harness.supervisor._queue) == []
    assert harness.record().status is EmbeddingStatus.DONE


@pytest.mark.parametrize(
    ("exit_code", "error"),
    [
        (1, "STAGE_FAILED (exit=1)"),
        (137, "STAGE_FAILED (exit=137)"),
        (-9, "STAGE_FAILED (signal=9)"),
        (2, "OLLAMA_UNAVAILABLE"),
    ],
)
def test_failed_child_records_error_and_releases_models(
    embedding_harness: EmbeddingHarness,
    exit_code: int,
    error: str,
) -> None:
    harness = embedding_harness
    (harness.course_dir / "embed.exit").write_text(str(exit_code))
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.record().status is EmbeddingStatus.FAILED)
    wait_for(predicate=lambda: harness.supervisor._gpu_arbiter.status() == (None, None))
    assert harness.record().error == error
    assert harness.released == [("chat:9b", 0), ("test", 0)]


def test_successful_child_persists_progress_and_unloads(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.record().status is EmbeddingStatus.DONE)
    wait_for(predicate=lambda: harness.supervisor._gpu_arbiter.status() == (None, None))
    assert (harness.record().processed, harness.record().total) == (33, 33)
    assert harness.released == [("chat:9b", 0), ("test", 0)]


def test_estimation_model_unavailable_fails_without_launch(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = embedding_harness

    def unavailable(course_dir: object) -> float:
        raise EmbeddingUnavailableError(reason="model_missing")

    monkeypatch.setattr(embedding_supervisor, "estimate_embed_seconds", unavailable)
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.record().status is EmbeddingStatus.FAILED)
    assert harness.record().error == "OLLAMA_UNAVAILABLE"
    assert harness.released == []
    assert not (harness.course_dir / "embed.started").exists()


@pytest.mark.parametrize(
    "content", ['{"status":"running","processed":null,"total":3,"error":null}', "null"]
)
def test_recovery_skips_malformed_record_and_recovers_valid_course(
    embedding_harness: EmbeddingHarness,
    content: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = embedding_harness
    create_embed(course_dir=harness.course_dir)
    corrupted = harness.store.courses_dir / "corrupted"
    corrupted.mkdir()
    (corrupted / "embedding.json").write_text(content)
    harness.supervisor.recover_on_boot()
    assert len(harness.supervisor._queue) == 1
    assert harness.supervisor._queue[0].course_id == harness.course_dir.name
    assert "Unreadable embedding run" in caplog.text
