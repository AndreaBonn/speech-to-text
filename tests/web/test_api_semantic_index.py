from dataclasses import replace

import pytest
from semantic_index_fixtures import (
    BACKFILL_URL,
    BASE_URL,
    CATALOG_URL,
    MODEL,
    STATUS_URL,
    SemanticHarness,
    semantic_harness,
)
from vector_reconcile_fixtures import FakeEmbedder, write_course, write_pages

from sbobina import ollama_embed
from sbobina.ollama_embed import ModelStatus
from sbobina.web.embedding_store import (
    EmbeddingStatus,
    create_embed,
    finish_embed,
    save_embed,
)
from sbobina.web.vector_reconcile import CourseEmbedding, EmbeddingConfig, embed_course
from sbobina.web.vector_store import StoredVector

__all__ = ["semantic_harness"]


def _prepare_partial_course(h: SemanticHarness) -> None:
    course = write_course(store=h.store)
    write_pages(store=h.store, course=course, texts=["cached"])
    context = CourseEmbedding(
        store=h.store,
        vectors=h.vectors,
        embedding=EmbeddingConfig(
            model=MODEL,
            status=ModelStatus(digest="digest", dimensions=2),
            embedder=FakeEmbedder(truncated_text="cached"),
        ),
    )
    embed_course(context=context, course_key=course.key, progress=lambda update: None)
    directory = h.store.courses_dir / course.id
    save_embed(
        course_dir=directory,
        record=replace(
            create_embed(course_dir=directory), status=EmbeddingStatus.RUNNING
        ),
    )
    finish_embed(course_dir=directory, status=EmbeddingStatus.DONE)
    write_pages(store=h.store, course=course, texts=["missing"])
    h.client.post(f"/api/v1/courses/{course.key}/semantic-index")


def test_status_reports_coverage_missing_truncation_and_last_success(
    semantic_harness: SemanticHarness,
) -> None:
    h = semantic_harness
    _prepare_partial_course(h=h)
    response = h.client.get(STATUS_URL)
    assert response.status_code == 200
    data = response.json()["data"]
    assert (
        data["model"],
        data["installed"],
        data["dimensions"],
        data["measured"],
        data["semantic_search"],
        data["model_change_pending"],
    ) == (MODEL, True, 2, True, True, False)
    item = data["courses"][0]
    assert item["coverage"] == {"embedded": 1, "total": 1, "truncated": 1}
    assert item["missing_units"] == 1 and item["estimated_seconds"] == 1.0
    assert item["last_indexed_at"] is not None and item["queued_action"] == "embed"
    assert item["run"]["status"] == "queued"
    assert (
        data["size_bytes"]
        == (h.store.jobs_dir.parent / "vectors.sqlite3").stat().st_size
    )


@pytest.mark.parametrize("reason", ["model_missing", "unreachable", "bad_response"])
def test_status_unavailability_is_data(
    semantic_harness: SemanticHarness, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    def unavailable(**kwargs: object) -> ModelStatus:
        raise ollama_embed.EmbeddingUnavailableError(reason=reason)

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    write_course(store=semantic_harness.store)
    response = semantic_harness.client.get(STATUS_URL)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["installed"] is False and data["reason"] == reason
    assert data["dimensions"] is None and data["courses"][0]["coverage"] is None


def test_post_course_queues_live_and_rejects_duplicate_or_missing(
    semantic_harness: SemanticHarness,
) -> None:
    h = semantic_harness
    course = write_course(store=h.store)
    url = f"/api/v1/courses/{course.key}/semantic-index"
    assert h.client.post(url).status_code == 202
    assert [(item.action, item.course_id) for item in h.supervisor._queue] == [
        ("embed", course.id)
    ]
    duplicate = h.client.post(url)
    assert (
        duplicate.status_code == 409
        and duplicate.json()["error"]["code"] == "EMBED_ALREADY_QUEUED"
    )
    missing = h.client.post("/api/v1/courses/absent/semantic-index")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "url", [BACKFILL_URL, "/api/v1/courses/diritto/semantic-index"]
)
@pytest.mark.parametrize("origin", [None, "http://foreign.invalid"])
def test_mutations_require_own_origin(
    semantic_harness: SemanticHarness, url: str, origin: str | None
) -> None:
    h = semantic_harness
    write_course(store=h.store)
    h.client.headers.pop("Origin")
    response = h.client.post(
        url,
        json={"confirm_model_change": False},
        headers={"Origin": origin} if origin else {},
    )
    assert (
        response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"
    )
    accepted = h.client.post(
        url, json={"confirm_model_change": False}, headers={"Origin": BASE_URL}
    )
    assert accepted.status_code == 202


def test_read_origin_is_optional_but_foreign_is_rejected(
    semantic_harness: SemanticHarness,
) -> None:
    client = semantic_harness.client
    client.headers.pop("Origin")
    assert client.get(STATUS_URL).status_code == 200
    assert (
        client.get(STATUS_URL, headers={"Origin": "http://foreign.invalid"}).status_code
        == 403
    )


def test_backfill_confirmation_queues_live_with_selected_model(
    semantic_harness: SemanticHarness,
) -> None:
    h = semantic_harness
    course = write_course(store=h.store)
    write_pages(store=h.store, course=course, texts=["new"])
    h.vectors.put_vectors(
        model_key="old",
        vectors=[StoredVector(text_sha256="old", vector=(1.0, 0.0), truncated=False)],
    )
    response = h.client.post(BACKFILL_URL, json={"confirm_model_change": False})
    assert response.json()["data"] == {"model_change_pending": True, "queued": 0}
    assert list(h.supervisor._queue) == []
    accepted = h.client.post(BACKFILL_URL, json={"confirm_model_change": True})
    assert accepted.status_code == 202 and accepted.json()["data"]["queued"] == 1
    assert [item.course_id for item in h.supervisor._queue] == [course.id]
    assert (
        h.client.post(BACKFILL_URL, json={"confirm_model_change": True}).json()["data"][
            "queued"
        ]
        == 0
    )


def test_backfill_missing_model_is_conflict(
    semantic_harness: SemanticHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(**kwargs: object) -> ModelStatus:
        raise ollama_embed.EmbeddingUnavailableError(reason="model_missing")

    monkeypatch.setattr(ollama_embed, "model_status", unavailable)
    response = semantic_harness.client.post(
        BACKFILL_URL, json={"confirm_model_change": True}
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "model_missing"
    )


def test_catalog_recommended_and_unmeasured(semantic_harness: SemanticHarness) -> None:
    response = semantic_harness.client.get(CATALOG_URL)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "available",
        "models": [
            {"model": MODEL, "recommended": True, "measured": True},
            {"model": "other", "recommended": False, "measured": False},
        ],
    }


def test_catalog_offline_is_empty_state(
    semantic_harness: SemanticHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(**kwargs: object) -> object:
        raise ConnectionError("private connection details")

    monkeypatch.setattr(ollama_embed, "Client", offline)
    response = semantic_harness.client.get(CATALOG_URL)
    assert response.status_code == 200
    assert response.json()["data"] == {"status": "unreachable", "models": []}


def test_backfill_uses_saved_model_in_app_config_dir(
    semantic_harness: SemanticHarness,
) -> None:
    h = semantic_harness
    course = write_course(store=h.store)
    write_pages(store=h.store, course=course, texts=["indexed"])
    context = CourseEmbedding(
        store=h.store,
        vectors=h.vectors,
        embedding=EmbeddingConfig(
            model="other",
            status=ModelStatus(digest="digest", dimensions=2),
            embedder=FakeEmbedder(),
        ),
    )
    embed_course(context=context, course_key=course.key, progress=lambda update: None)
    saved = h.client.put(
        "/api/v1/settings/semantic-index",
        json={"embedding_model": "other", "semantic_search": False},
    )
    assert saved.status_code == 200
    response = h.client.post(BACKFILL_URL, json={"confirm_model_change": False})
    assert response.json()["data"] == {"model_change_pending": False, "queued": 0}
    data = h.client.get(STATUS_URL).json()["data"]
    assert data["model"] == "other" and data["semantic_search"] is False
    assert data["measured"] is False and data["courses"][0]["missing_units"] == 0


def test_status_and_catalog_probe_ollama_with_short_timeout(
    semantic_harness: SemanticHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[float] = []

    def status(**kwargs: float) -> ModelStatus:
        timeouts.append(kwargs["timeout_s"])
        return ModelStatus(digest="digest", dimensions=2)

    def catalog(**kwargs: float) -> list[str]:
        timeouts.append(kwargs["timeout_s"])
        return []

    monkeypatch.setattr(ollama_embed, "model_status", status)
    monkeypatch.setattr(ollama_embed, "list_embedding_models", catalog)
    assert semantic_harness.client.get(STATUS_URL).status_code == 200
    assert semantic_harness.client.get(CATALOG_URL).status_code == 200
    assert timeouts and all(value <= 2.0 for value in timeouts)
