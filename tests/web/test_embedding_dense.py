from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from dense_retrieval_fixtures import COURSE, document, populate, ranker
from hybrid_runtime_fixtures import enable_factory
from ollama_embed_fixtures import FakeClient

from sbobina.settings import Settings
from sbobina.web import dense_factory
from sbobina.web.embedding_supervisor import EMBEDDING_STAGE
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError


def test_rank_writer_skips_embedding_and_recovers(tmp_path: Path) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    arbiter = GpuArbiter()
    with arbiter.transcription_lease(stage=EMBEDDING_STAGE):
        result, report = dense.rank(
            course=COURSE, passages=passages, question="contratto", arbiter=arbiter
        )
        assert (result, report.mode, report.reason) == ([], "bm25", "gpu_busy")
        assert client.calls == []
    result, report = dense.rank(
        course=COURSE, passages=passages, question="contratto", arbiter=arbiter
    )
    assert (result, report.mode) == (passages, "dense")
    assert len(client.calls) == 1
    vectors.close()


@pytest.mark.parametrize("stage", ["transcribing", "TRANSCRIBING", "custom-stage"])
def test_rank_non_embedding_writer_queries_cpu_without_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    arbiter = GpuArbiter()
    lease = Mock(side_effect=AssertionError("CPU query requested a GPU lease"))
    monkeypatch.setattr(arbiter, "chat_turn", lease)
    with arbiter.transcription_lease(stage=stage):
        result, report = dense.rank(
            course=COURSE, passages=passages, question="contratto", arbiter=arbiter
        )
    assert (result, report.mode, report.reason) == (passages, "dense", None)
    assert client.calls[0]["options"]["num_gpu"] == 0
    assert lease.call_count == 0
    vectors.close()


@pytest.mark.parametrize(
    "stage,mode", [(EMBEDDING_STAGE, "bm25"), ("TRANSCRIBING", "dense")]
)
def test_rank_writer_race_respects_busy_error_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, mode: str
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    arbiter = GpuArbiter()
    lease = Mock(side_effect=GpuBusyError(stage=stage, estimate_s=None))
    monkeypatch.setattr(arbiter, "chat_turn", lease)
    result, report = dense.rank(
        course=COURSE, passages=passages, question="contratto", arbiter=arbiter
    )
    assert report.mode == mode
    assert lease.call_count == 1
    if stage == EMBEDDING_STAGE:
        assert (result, report.reason, client.calls) == ([], "gpu_busy", [])
    else:
        assert (result, report.reason) == (passages, None)
        assert client.calls[0]["options"]["num_gpu"] == 0
    vectors.close()


def test_rank_waiting_writer_skips_embedding(tmp_path: Path) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    arbiter = GpuArbiter()
    acquired = Event()

    def writer() -> None:
        with arbiter.transcription_lease(stage="embedding"):
            acquired.set()

    with arbiter.chat_turn():
        thread = Thread(target=writer)
        thread.start()
        with arbiter._condition:
            assert arbiter._condition.wait_for(
                predicate=lambda: arbiter._writer_waiting, timeout=5
            )
        _, report = dense.rank(
            course=COURSE, passages=passages, question="contratto", arbiter=arbiter
        )
        assert report.reason == "gpu_busy" and client.calls == []
    thread.join(timeout=5)
    assert acquired.is_set()
    _, report = dense.rank(
        course=COURSE, passages=passages, question="contratto", arbiter=arbiter
    )
    assert report.mode == "dense" and len(client.calls) == 1
    vectors.close()


@pytest.mark.parametrize(
    "stage,label",
    [
        ("embedding", "un'indicizzazione semantica"),
        ("transcribing", "una trascrizione"),
        ("custom-stage", "custom-stage"),
    ],
)
def test_gpu_busy_message_uses_stage_label(stage: str, label: str) -> None:
    error = GpuBusyError(stage=stage, estimate_s=20.0)
    assert error.message == f"GPU occupata da {label} ({stage})"
    assert (error.code, error.stage, error.estimate_s) == ("GPU_BUSY", stage, 20.0)


def test_vector_store_for_process_reuses_the_factory_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_factory(monkeypatch=monkeypatch, client=FakeClient())
    vectors = dense_factory.vector_store_for_process(data_dir=tmp_path)
    runtime = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert runtime.ranker is not None and runtime.ranker._vectors is vectors
    assert dense_factory.vector_store_for_process(data_dir=tmp_path / ".") is vectors


def test_rank_busy_reason_takes_priority_during_incomplete_index(
    tmp_path: Path,
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    arbiter = GpuArbiter()
    with arbiter.transcription_lease(stage="embedding"):
        _, report = dense.rank(
            course=COURSE, passages=passages, question="contratto", arbiter=arbiter
        )
    assert report.reason == "gpu_busy" and client.calls == []
    _, report = dense.rank(course=COURSE, passages=passages, question="contratto")
    assert report.reason == "not_indexed"
    vectors.close()
