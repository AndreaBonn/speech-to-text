from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest
from dense_retrieval_fixtures import MODEL, STATUS
from ollama_embed_fixtures import FakeClient

from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.settings import Settings
from sbobina.web.dense_factory import RECHECK_INTERVAL_S
from sbobina.web.vector_store import VectorStore


def test_disabled_factory_skips_network_and_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    status = Mock(side_effect=AssertionError("Disabled retrieval contacted Ollama"))
    monkeypatch.setattr(dense_factory, "model_status", status)
    runtime = dense_factory.dense_for_process(
        settings=Settings(semantic_search=False),
        data_dir=tmp_path,
    )
    assert (runtime.ranker, runtime.reason) == (None, "disabled")
    assert status.call_count == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("reason", ["model_missing", "unreachable", "bad_response"])
def test_factory_preserves_unavailable_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    from sbobina.web import dense_factory

    status = Mock(side_effect=EmbeddingUnavailableError(reason=reason))
    monkeypatch.setattr(dense_factory, "model_status", status)
    current = Settings()
    runtime = dense_factory.dense_for_process(settings=current, data_dir=tmp_path)
    assert (runtime.ranker, runtime.reason, runtime.model) == (None, reason, MODEL)
    status.assert_called_once_with(
        host="http://localhost:11434",
        model=MODEL,
        timeout_s=current.embedding_timeout_s,
    )


def test_concurrent_factory_opens_one_store_and_builds_one_ranker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    barrier = Barrier(parties=8)
    status = Mock(return_value=STATUS)
    vector_store = Mock(wraps=VectorStore)
    client = FakeClient()
    monkeypatch.setattr(dense_factory, "model_status", status)
    monkeypatch.setattr(dense_factory, "VectorStore", vector_store)
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=client))

    def build(_: int) -> object:
        barrier.wait(timeout=5)
        return dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(build, range(8)))
    assert len({id(result) for result in results}) == 1
    assert status.call_count == vector_store.call_count == 1
    assert results[0] is not None and client.pull_calls == 0


def test_factory_recovers_after_missing_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    monkeypatch.setattr(
        dense_factory,
        "model_status",
        Mock(
            side_effect=[
                EmbeddingUnavailableError(reason="model_missing"),
                STATUS,
            ]
        ),
    )
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=FakeClient()))
    missing = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    recovered = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert missing.reason == "model_missing"
    assert recovered.ranker is not None and recovered.reason is None


def test_factory_passes_embedding_timeout_to_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    client = Mock(return_value=FakeClient())
    monkeypatch.setattr(dense_factory, "model_status", Mock(return_value=STATUS))
    monkeypatch.setattr(dense_factory, "Client", client)
    settings = Settings()
    runtime = dense_factory.dense_for_process(settings=settings, data_dir=tmp_path)
    assert runtime.ranker is not None
    assert "timeout" in client.call_args.kwargs
    client.assert_called_once_with(
        host=settings.ollama_host,
        timeout=settings.embedding_timeout_s,
    )


def test_factory_rechecks_unchanged_digest_after_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    now = 0.0
    status = Mock(return_value=STATUS)
    monkeypatch.setattr(dense_factory, "_clock", lambda: now, raising=False)
    monkeypatch.setattr(dense_factory, "model_status", status)
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=FakeClient()))
    first = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    now += RECHECK_INTERVAL_S + 1
    second = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert status.call_count == 2
    assert second is first
    now += RECHECK_INTERVAL_S / 2
    assert (
        dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path) is first
    )
    assert status.call_count == 2


def test_factory_rebuilds_changed_digest_after_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    now = 0.0
    status = Mock(side_effect=[STATUS, replace(STATUS, digest="other-digest")])
    vector_store = Mock(wraps=VectorStore)
    monkeypatch.setattr(dense_factory, "_clock", lambda: now, raising=False)
    monkeypatch.setattr(dense_factory, "model_status", status)
    monkeypatch.setattr(dense_factory, "VectorStore", vector_store)
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=FakeClient()))
    first = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    now += RECHECK_INTERVAL_S + 1
    second = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert second.ranker is not first.ranker
    assert first.ranker is not None and second.ranker is not None
    assert second.ranker._model_key != first.ranker._model_key
    assert status.call_count == 2
    assert vector_store.call_count == 1


def test_factory_skips_recheck_before_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sbobina.web import dense_factory

    now = 0.0
    status = Mock(return_value=STATUS)
    monkeypatch.setattr(dense_factory, "_clock", lambda: now, raising=False)
    monkeypatch.setattr(dense_factory, "model_status", status)
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=FakeClient()))
    first = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    now += RECHECK_INTERVAL_S / 2
    second = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert status.call_count == 1
    assert second is first


@pytest.mark.parametrize("reason", ["model_missing", "unreachable", "bad_response"])
def test_factory_keeps_cached_ranker_after_recheck_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    from sbobina.web import dense_factory

    now = 0.0
    status = Mock(
        side_effect=[STATUS, EmbeddingUnavailableError(reason=reason), STATUS]
    )
    monkeypatch.setattr(dense_factory, "_clock", lambda: now, raising=False)
    monkeypatch.setattr(dense_factory, "model_status", status)
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=FakeClient()))
    first = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    now += RECHECK_INTERVAL_S + 1
    second = dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path)
    assert second is first
    assert status.call_count == 2
    now += RECHECK_INTERVAL_S / 2
    assert (
        dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path) is first
    )
    assert status.call_count == 2
    now += RECHECK_INTERVAL_S
    assert (
        dense_factory.dense_for_process(settings=Settings(), data_dir=tmp_path) is first
    )
    assert status.call_count == 3
