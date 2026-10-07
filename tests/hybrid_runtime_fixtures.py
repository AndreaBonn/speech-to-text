from unittest.mock import Mock

import pytest
from dense_retrieval_fixtures import MODEL, STATUS, populate, ranker
from ollama_embed_fixtures import FakeClient

from sbobina.web import dense_factory
from sbobina.web.course_retrieval import course_scope, sample_course
from sbobina.web.dense_factory import DenseRuntime
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session


def indexed_runtime(store: JobStore) -> tuple[DenseRuntime, FakeClient]:
    dense, vectors, client = ranker(tmp_path=store.jobs_dir.parent)
    with search_session(
        store=store, path=store.jobs_dir.parent / "search.sqlite3"
    ) as index:
        passages = sample_course(
            store=store,
            index=index,
            scope=course_scope(store=store, key="diritto"),
            budget_words=10000,
        )
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)] * len(passages))
    dense_factory._VECTORS[store.jobs_dir.parent / "vectors.sqlite3"] = vectors
    return DenseRuntime(ranker=dense, reason=None, model=MODEL), client


def enable_factory(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(dense_factory, "model_status", Mock(return_value=STATUS))
    monkeypatch.setattr(dense_factory, "Client", Mock(return_value=client))
