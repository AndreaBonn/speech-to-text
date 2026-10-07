from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness
from test_supervisor import wait_for

from sbobina.ollama_embed import ModelStatus
from sbobina.web import course_actions, embedding_supervisor, gpu_release
from sbobina.web.embedding_store import EmbeddingStatus
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.vector_reconcile import embedding_model_key
from sbobina.web.vector_store import Coverage, VectorStore

__all__ = ["embedding_harness"]


@pytest.mark.parametrize("stop", [False, True])
def test_cancel_or_stop_terminates_child_preserving_committed_batch(
    embedding_harness: EmbeddingHarness,
    stop: bool,
) -> None:
    harness = embedding_harness
    (harness.course_dir / "hold").touch()
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    wait_for(predicate=(harness.course_dir / "batch.saved").exists)
    child = harness.supervisor._process
    assert child is not None and child.poll() is None
    assert (harness.record().processed, harness.record().total) == (32, 33)
    with (
        pytest.raises(GpuBusyError) as caught,
        harness.supervisor._gpu_arbiter.chat_turn(),
    ):
        pass
    assert (caught.value.stage, caught.value.estimate_s) == ("embedding", 10.0)
    if stop:
        harness.supervisor.stop()
    else:
        course_actions.cancel_embed(supervisor=harness.supervisor, course_key="diritto")
    wait_for(predicate=lambda: harness.supervisor._gpu_arbiter.status() == (None, None))
    assert child.poll() is not None
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert harness.released == [("chat:9b", 0), ("test", 0)]
    _assert_committed_batch(harness=harness)


def _assert_committed_batch(harness: EmbeddingHarness) -> None:
    vectors = VectorStore(path=harness.store.courses_dir.parent / "vectors.sqlite3")
    key = embedding_model_key(
        model="test", status=ModelStatus(digest="digest", dimensions=2)
    )
    assert vectors.coverage(course="diritto", model_key=key) == Coverage(32, 33, 0)


@pytest.mark.parametrize("stop", [False, True])
def test_cancel_or_stop_waiting_lease_prevents_spawn(
    embedding_harness: EmbeddingHarness,
    stop: bool,
) -> None:
    harness = embedding_harness
    arbiter = harness.supervisor._gpu_arbiter
    with arbiter.chat_turn():
        course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
        harness.supervisor.start()
        wait_for(predicate=lambda: arbiter.status()[0] == "embedding")
        assert harness.record().status is EmbeddingStatus.RUNNING
        if stop:
            harness.supervisor.stop()
        else:
            course_actions.cancel_embed(
                supervisor=harness.supervisor, course_key="diritto"
            )
        wait_for(predicate=lambda: arbiter.status() == (None, None))
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert not (harness.course_dir / "embed.started").exists()
    assert harness.released == []


def test_cancel_during_initial_unload_prevents_spawn(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = embedding_harness
    entered, release = Event(), Event()

    def unload(host: str) -> None:
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(gpu_release, "unload_ollama_models", unload)
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    try:
        assert entered.wait(timeout=5)
        course_actions.cancel_embed(supervisor=harness.supervisor, course_key="diritto")
    finally:
        release.set()
        harness.supervisor.stop()
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert not (harness.course_dir / "embed.started").exists()


def test_spawn_failure_unloads_and_fails_run(
    embedding_harness: EmbeddingHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = embedding_harness

    def fail(**kwargs: object) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr(embedding_supervisor, "_spawn", fail)
    course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
    harness.supervisor.start()
    wait_for(predicate=lambda: harness.record().status is EmbeddingStatus.FAILED)
    assert harness.record().error == "SUPERVISOR_ERROR"
    assert harness.released == [("chat:9b", 0), ("test", 0)]
    assert harness.supervisor._gpu_arbiter.status() == (None, None)


def _paused_arbiter(entered: Event, release: Event) -> GpuArbiter:
    class PausedArbiter(GpuArbiter):
        @contextmanager
        def transcription_lease(
            self,
            stage: str,
            estimate_s: float | None = None,
            *,
            cancellation: Event | None = None,
        ) -> Iterator[None]:
            entered.set()
            assert release.wait(timeout=5)
            with super().transcription_lease(
                stage=stage, estimate_s=estimate_s, cancellation=cancellation
            ):
                yield

    return PausedArbiter()


def test_cancel_before_lease_registration_does_not_wait_for_reader(
    embedding_harness: EmbeddingHarness,
) -> None:
    harness = embedding_harness
    entered, release = Event(), Event()

    arbiter = _paused_arbiter(entered=entered, release=release)
    harness.supervisor._gpu_arbiter = arbiter
    with arbiter.chat_turn():
        course_actions.submit_embed(supervisor=harness.supervisor, course_key="diritto")
        harness.supervisor.start()
        assert entered.wait(timeout=5)
        course_actions.cancel_embed(supervisor=harness.supervisor, course_key="diritto")
        release.set()
        wait_for(predicate=lambda: harness.supervisor._active is None)
    assert harness.record().status is EmbeddingStatus.CANCELLED
    assert harness.released == []
