from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from ollama import EmbedResponse
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    write_course,
    write_pages,
)

from sbobina.embedding_units import content_hash
from sbobina.ollama_embed import ModelStatus
from sbobina.settings import settings
from sbobina.web import embedding_runner
from sbobina.web.embedding_runner import run_embed
from sbobina.web.embedding_store import (
    EmbeddingStatus,
    create_embed,
    load_embed,
    save_embed,
)
from sbobina.web.vector_reconcile import EmbeddingProgress, embed_course
from sbobina.web.vector_store import Coverage, StoredVector


def _running(course_dir: Path) -> None:
    record = create_embed(course_dir=course_dir)
    save_embed(
        course_dir=course_dir, record=replace(record, status=EmbeddingStatus.RUNNING)
    )


def test_run_embed_persists_progress_before_return_and_done(tmp_path: Path) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    course_dir = context.store.courses_dir / course.id
    _running(course_dir=course_dir)

    def embed(
        *, course_key: str, progress: Callable[[EmbeddingProgress], None]
    ) -> EmbeddingProgress:
        assert course_key == course.key
        update = EmbeddingProgress(
            processed=32, total=40, truncated=0, units_per_second=2
        )
        progress(update)
        record = load_embed(course_dir=course_dir)
        assert record is not None
        assert (record.processed, record.total) == (32, 40)
        assert record.status == EmbeddingStatus.RUNNING
        return replace(update, processed=40)

    run_embed(course_dir=course_dir, embed=embed)
    record = load_embed(course_dir=course_dir)
    assert record is not None
    assert (record.processed, record.total) == (40, 40)
    assert record.status == EmbeddingStatus.DONE


def test_run_embed_propagates_failure_and_preserves_committed_batch(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder(fail_batch=2))
    course = write_course(store=context.store)
    write_pages(
        store=context.store, course=course, texts=[f"Pagina {n}" for n in range(40)]
    )
    course_dir = context.store.courses_dir / course.id
    _running(course_dir=course_dir)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_embed(course_dir=course_dir, embed=partial(embed_course, context=context))
    record = load_embed(course_dir=course_dir)
    assert record is not None
    assert (record.status, record.processed, record.total) == (
        EmbeddingStatus.RUNNING,
        32,
        40,
    )
    assert context.vectors.coverage(
        course=course.key, model_key=context.embedding.model_key
    ) == Coverage(embedded=32, total=40, truncated=0)


def _available_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embedding_runner,
        "model_status",
        lambda **kwargs: ModelStatus(digest="test-digest", dimensions=2),
    )


def test_estimate_embed_reads_fresh_missing_units_without_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["A", "B", "C"])
    course_dir = context.store.courses_dir / course.id
    _available_model(monkeypatch=monkeypatch)
    assert embedding_runner.estimate_embed_seconds(
        course_dir=course_dir
    ) == pytest.approx(3 / 1.7)
    context.vectors.put_vectors(
        model_key=context.embedding.model_key,
        vectors=[
            StoredVector(
                text_sha256=content_hash("A"), vector=(1.0, 1.0), truncated=False
            )
        ],
    )
    assert embedding_runner.estimate_embed_seconds(
        course_dir=course_dir
    ) == pytest.approx(2 / 1.7)
    write_pages(store=context.store, course=course, texts=["D"])
    assert embedding_runner.estimate_embed_seconds(
        course_dir=course_dir
    ) == pytest.approx(3 / 1.7)


class _EmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def embed(self, **kwargs: Any) -> EmbedResponse:
        self.calls.append(kwargs)
        return EmbedResponse(embeddings=[[1.0, 1.0] for _ in kwargs["input"]])


def test_run_embed_stage_uses_document_embedding_and_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Materiale"])
    course_dir = context.store.courses_dir / course.id
    client = _EmbeddingClient()
    _available_model(monkeypatch=monkeypatch)
    monkeypatch.setattr(embedding_runner, "Client", lambda **kwargs: client)
    _running(course_dir=course_dir)
    embedding_runner.run_embed_stage(course_dir=course_dir)
    record = load_embed(course_dir=course_dir)
    assert record is not None
    assert (record.processed, record.total) == (1, 1)
    assert record.status == EmbeddingStatus.DONE
    _running(course_dir=course_dir)
    embedding_runner.run_embed_stage(course_dir=course_dir)
    assert len(client.calls) == 1
    assert client.calls[0] == {
        "model": "qwen3-embedding:8b",
        "input": ["Materiale"],
        "options": {"num_ctx": 2048},
        "truncate": False,
    }


@pytest.mark.parametrize("configured,expected", [(30.0, 180.0), (240.0, 240.0)])
def test_run_embed_stage_allows_measured_batch_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: float, expected: float
) -> None:
    monkeypatch.setattr(settings, "embedding_timeout_s", configured)

    def client(*, host: str, timeout: float) -> _EmbeddingClient:
        assert timeout == expected
        raise RuntimeError("client checked")

    monkeypatch.setattr(embedding_runner, "Client", client)
    with pytest.raises(RuntimeError, match="client checked"):
        embedding_runner.run_embed_stage(course_dir=tmp_path)
