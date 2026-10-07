from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ollama import ListResponse, ShowResponse

from sbobina import ollama_embed
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.dense_factory import vector_store_for_process
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor
from sbobina.web.vector_store import VectorStore

BASE_URL = "http://127.0.0.1:8765"
STATUS_URL = "/api/v1/semantic-index/status"
BACKFILL_URL = "/api/v1/semantic-index/backfill"
CATALOG_URL = "/api/v1/settings/embedding-models"
MODEL = "qwen3-embedding:8b"


class SemanticClient:
    def __init__(self, **kwargs: object) -> None:
        pass

    def list(self) -> ListResponse:
        return ListResponse(
            models=[
                ListResponse.Model(model=name, digest="digest")
                for name in (MODEL, "other", "chat")
            ]
        )

    def show(self, *, model: str) -> ShowResponse:
        return ShowResponse(
            model_info={"test.embedding_length": 2},
            capabilities=["completion"] if model == "chat" else ["embedding"],
        )


@dataclass
class SemanticHarness:
    client: TestClient
    store: JobStore
    supervisor: Supervisor
    vectors: VectorStore


@pytest.fixture
def semantic_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[SemanticHarness]:
    monkeypatch.setattr(ollama_embed, "Client", SemanticClient)
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    app = create_app(settings=settings)
    client = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield SemanticHarness(
        client=client,
        store=app.state.job_store,
        supervisor=app.state.supervisor,
        vectors=vector_store_for_process(data_dir=settings.data_dir),
    )
    client.close()
