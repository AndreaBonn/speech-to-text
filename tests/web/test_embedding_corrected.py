from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_api_corrected import _job, _revision, _store, client
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    write_course,
    write_pages,
)

from sbobina import ollama_embed
from sbobina.models import load_transcript
from sbobina.ollama_embed import EmbeddingUnavailableError, ModelStatus
from sbobina.settings import settings
from sbobina.web import course_actions
from sbobina.web.embedding_store import EmbeddingStatus, load_embed
from sbobina.web.job_models import JobRecord
from sbobina.web.supervisor import Supervisor
from sbobina.web.vector_reconcile import embed_course

__all__ = ["client"]


@pytest.fixture(autouse=True)
def available_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "semantic_search", True)
    monkeypatch.setattr(
        ollama_embed,
        "model_status",
        lambda **kw: ModelStatus(digest="test", dimensions=2),
    )


def _edit(client: TestClient, record: JobRecord) -> None:
    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 0,
            "end": 3,
            "expected": "Il processo è",
            "text": "Un possesso era",
            "revision": _revision(client=client, record=record),
        },
    )
    assert response.status_code == 200


def _supervisor(client: TestClient) -> Supervisor:
    supervisor: Supervisor = cast(FastAPI, client.app).state.supervisor
    return supervisor


def test_edit_corrected_three_words_queues_once_recomputes_only_changed_unit(
    client: TestClient, tmp_path: Path
) -> None:
    store = _store(client=client)
    course = write_course(store=store)
    write_pages(store=store, course=course, texts=["Documento invariato"])
    record, _ = _job(client=client, subject="Diritto")
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    embed_course(context=context, course_key=course.key, progress=lambda _: None)
    assert sum(len(batch) for batch in fake.calls) == 2
    fake.calls.clear()
    _edit(client=client, record=record)
    queue = _supervisor(client=client)._queue
    assert len(queue) == 1
    assert queue[0].action == "embed"
    embed_course(context=context, course_key=course.key, progress=lambda _: None)
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 1
    assert "Un possesso era" in fake.calls[0][0].text


def test_edit_corrected_missing_model_saves_failure_then_queues_when_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(client=client)
    course = write_course(store=store)
    first, _ = _job(client=client, subject="Diritto")

    def unavailable(**kwargs: object) -> ModelStatus:
        raise EmbeddingUnavailableError(reason="model_missing")

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    _edit(client=client, record=first)
    assert list(_supervisor(client=client)._queue) == []
    run = load_embed(course_dir=store.courses_dir / course.id)
    assert run is not None and run.status is EmbeddingStatus.FAILED
    assert run.error == "model_missing"
    monkeypatch.setattr(
        ollama_embed,
        "model_status",
        lambda **kw: ModelStatus(digest="test", dimensions=2),
    )
    second, _ = _job(client=client, subject="Diritto")
    _edit(client=client, record=second)
    assert len(_supervisor(client=client)._queue) == 1


def test_update_meta_after_edit_does_not_enqueue_embedding(client: TestClient) -> None:
    store = _store(client=client)
    course = write_course(store=store)
    record, _ = _job(client=client, subject="Diritto")
    supervisor = _supervisor(client=client)
    _edit(client=client, record=record)
    assert len(supervisor._queue) == 1
    course_actions.cancel_embed(supervisor=supervisor, course_key=course.key)
    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/meta", json={"course": "Economia"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["course"] == "Economia"
    assert list(supervisor._queue) == []


def test_edit_corrected_legacy_expanded_subject_preserves_save(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    legacy, directory = _job(client=client, subject="ﬃ" * 34)
    _edit(client=client, record=legacy)
    saved = load_transcript(path=directory / "audio.corretto.json")
    assert [word.text.strip() for word in saved.words[:3]] == ["Un", "possesso", "era"]
    assert list(_supervisor(client=client)._queue) == []
    assert "Course label exceeds registry limit" in caplog.text
    regular, _ = _job(client=client, subject="Diritto")
    _edit(client=client, record=regular)
    assert len(_supervisor(client=client)._queue) == 1


def test_edit_corrected_enqueue_error_keeps_saved_edit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(client=client)
    write_course(store=store)
    record, directory = _job(client=client, subject="Diritto")

    def broken(**kwargs: object) -> ModelStatus:
        raise RuntimeError("unexpected client failure")

    monkeypatch.setattr(ollama_embed, "model_status", broken)
    _edit(client=client, record=record)

    assert "Automatic embedding enqueue failed" in caplog.text
    assert list(_supervisor(client=client)._queue) == []
    saved = load_transcript(path=directory / "audio.corretto.json")
    assert [word.text.strip() for word in saved.words[:3]] == ["Un", "possesso", "era"]
