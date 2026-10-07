from typing import cast

import pytest
from embedding_fixtures import EmbeddingHarness, embedding_harness
from fastapi import FastAPI
from semantic_index_fixtures import BACKFILL_URL, SemanticHarness, semantic_harness
from test_supervisor import wait_for

from sbobina.web.embedding_store import EmbeddingStatus

__all__ = ["embedding_harness", "semantic_harness"]


@pytest.mark.parametrize(
    "url", [BACKFILL_URL, "/api/v1/courses/diritto/semantic-index"]
)
def test_http_enqueue_wakes_running_supervisor_and_finishes(
    semantic_harness: SemanticHarness,
    embedding_harness: EmbeddingHarness,
    url: str,
) -> None:
    app = cast(FastAPI, semantic_harness.client.app)
    app.state.supervisor = embedding_harness.supervisor
    app.state.job_store = embedding_harness.store
    embedding_harness.supervisor.start()
    response = semantic_harness.client.post(url, json={"confirm_model_change": False})
    assert response.status_code == 202
    wait_for(
        predicate=lambda: embedding_harness.record().status is EmbeddingStatus.DONE
    )
    record = embedding_harness.record()
    assert record.processed == record.total == 33
    assert record.last_indexed_at is not None
    assert (embedding_harness.course_dir / "embed.started").is_file()
