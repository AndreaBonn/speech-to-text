from pathlib import Path
from typing import Any

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness
from ollama import EmbedResponse
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    write_course,
    write_pages,
)

from sbobina import cli_semantic, ollama_embed
from sbobina.config_dir import resolve_config_dir
from sbobina.ollama_embed import EmbeddingInput, ModelStatus
from sbobina.settings import settings
from sbobina.user_preferences import UserPreferences, preferences_path, save_preferences
from sbobina.web import embedding_runner, embedding_supervisor

__all__ = ["embedding_harness"]


def _save(*, enabled: bool) -> None:
    config_dir = resolve_config_dir(settings=settings)
    save_preferences(
        path=preferences_path(config_dir),
        preferences=UserPreferences(
            embedding_model="saved:latest", semantic_search=enabled
        ),
    )


def test_automatic_enqueue_reads_saved_toggle_and_model(
    embedding_harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def status(**kwargs: Any) -> ModelStatus:
        calls.append(kwargs["model"])
        return ModelStatus(digest="test", dimensions=2)

    monkeypatch.setattr(ollama_embed, "model_status", status)
    harness = embedding_harness
    _save(enabled=False)
    embedding_supervisor.maybe_enqueue_embed(
        supervisor=harness.supervisor, course_id=harness.course_dir.name
    )
    assert list(harness.supervisor._queue) == []
    assert calls == []
    _save(enabled=True)
    embedding_supervisor.maybe_enqueue_embed(
        supervisor=harness.supervisor, course_id=harness.course_dir.name
    )
    assert len(harness.supervisor._queue) == 1
    assert calls == ["saved:latest"]


def test_runner_estimate_probes_saved_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Page"])
    calls: list[str] = []

    def status(**kwargs: Any) -> ModelStatus:
        calls.append(kwargs["model"])
        return ModelStatus(digest="test", dimensions=2)

    monkeypatch.setattr(embedding_runner, "model_status", status)
    _save(enabled=True)
    estimate = embedding_runner.estimate_embed_seconds(
        course_dir=context.store.courses_dir / course.id
    )
    assert estimate == pytest.approx(1 / embedding_runner.EMBEDDING_UNITS_PER_SECOND)
    assert calls == ["saved:latest"]


class FakeClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    def embed(self, **kwargs: Any) -> EmbedResponse:
        self.models.append(kwargs["model"])
        return EmbedResponse(embeddings=[[1.0, 1.0] for _ in kwargs["input"]])


def test_cli_prepares_saved_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    probes: list[str] = []

    def status(**kwargs: Any) -> ModelStatus:
        probes.append(kwargs["model"])
        return ModelStatus(digest="test", dimensions=2)

    monkeypatch.setattr(cli_semantic, "Client", lambda **kwargs: client)
    monkeypatch.setattr(cli_semantic, "model_status", status)
    _save(enabled=True)
    embedding = cli_semantic._prepare_embedding()
    embedding.embedder([EmbeddingInput(text="Page", passage_id="p1")])
    assert embedding.model == "saved:latest"
    assert probes == ["saved:latest"]
    assert client.models == ["saved:latest"]


def test_runner_embeds_with_saved_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Page"])
    client = FakeClient()
    monkeypatch.setattr(embedding_runner, "Client", lambda **kwargs: client)
    monkeypatch.setattr(
        embedding_runner,
        "model_status",
        lambda **kwargs: ModelStatus(digest="test", dimensions=2),
    )
    _save(enabled=True)
    embedding_runner.run_embed_stage(course_dir=context.store.courses_dir / course.id)
    assert client.models == ["saved:latest"]


def test_cli_backfill_probes_saved_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes: list[str] = []

    def status(**kwargs: Any) -> ModelStatus:
        probes.append(kwargs["model"])
        return ModelStatus(digest="test", dimensions=2)

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli_semantic, "model_status", status)
    _save(enabled=True)
    result = cli_semantic._queue_backfill(confirm_model_change=False)
    assert result == 0
    assert probes == ["saved:latest"]
