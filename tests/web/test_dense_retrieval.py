from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from dense_retrieval_fixtures import (
    COURSE,
    MODEL,
    STATUS,
    document,
    lecture,
    populate,
    ranker,
)

from sbobina.embedding_units import content_hash
from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.web.vector_reconcile import embedding_model_key
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore


def test_rank_highest_cosine_is_first_after_fusion(tmp_path: Path) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    low, high = document(number=0), document(number=1)
    populate(vectors=vectors, passages=[low, high], values=[(0.6, 0.8), (1.0, 0.0)])

    result, report = dense.rank(
        course=COURSE, passages=[low, high], question="diritto?"
    )

    assert result == [high, low]
    assert (report.mode, report.reason, report.coverage) == (
        "dense",
        None,
        Coverage(embedded=2, total=2, truncated=0),
    )
    assert client.calls[0]["input"] == [
        "Instruct: Given a question, retrieve relevant passages that answer it\nQuery:diritto?"
    ]
    assert client.calls[0]["options"] == {"num_gpu": 0, "num_ctx": 2048}
    assert client.calls[0]["keep_alive"] == "30m"


def test_rank_keeps_fifty_candidates_per_source_before_fusion(tmp_path: Path) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    docs = [document(number=i) for i in range(60)]
    lectures = [lecture(number=i) for i in range(60)]
    populate(vectors=vectors, passages=docs + lectures, values=[(1.0, 0.0)] * 120)

    result, report = dense.rank(course=COURSE, passages=docs + lectures, question="x")

    assert report.mode == "dense"
    assert result == [
        item for pair in zip(docs[:50], lectures[:50], strict=True) for item in pair
    ]


@pytest.mark.parametrize("model,expected", [(MODEL, [0]), ("unmeasured", [0, 1])])
def test_rank_applies_only_the_model_threshold(
    tmp_path: Path, model: str, expected: list[int]
) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path, model=model)
    passages = [document(number=i) for i in range(2)]
    populate(
        vectors=vectors, passages=passages, values=[(1.0, 0.0), (0.4, 0.9)], model=model
    )

    result, _ = dense.rank(course=COURSE, passages=passages, question="x")

    assert result == [passages[i] for i in expected]


@pytest.mark.parametrize("count,reason", [(118, "partial"), (0, "not_indexed")])
def test_rank_incomplete_course_returns_bm25_report(
    tmp_path: Path, count: int, reason: str
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=i) for i in range(120)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)] * count)

    result, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", reason)
    assert report.coverage == Coverage(embedded=count, total=120, truncated=0)
    assert client.calls == []


@pytest.mark.parametrize("count", [0, 1, 2])
def test_rank_rebuild_needed_returns_bm25_report(tmp_path: Path, count: int) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=i) for i in range(2)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)] * count)
    before, before_report = dense.rank(course=COURSE, passages=passages, question="x")
    vectors.rebuild_needed = True

    result, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", "rebuild_needed")
    assert report.coverage == Coverage(embedded=count, total=2, truncated=0)
    assert before_report.reason == ("not_indexed", "partial", None)[count]
    assert before == (passages if count == 2 else [])
    assert len(client.calls) == (1 if count == 2 else 0)


def test_rank_unexpected_embedding_error_falls_back_to_bm25(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    client.failure = RuntimeError("boom")

    with caplog.at_level("ERROR"):
        result, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", "unreachable")
    assert report.coverage == Coverage(embedded=1, total=1, truncated=0)
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert error_records[0].exc_info is not None


def test_rank_successful_embedding_logs_no_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])

    with caplog.at_level("ERROR"):
        _, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert report.mode == "dense"
    assert [r for r in caplog.records if r.levelname == "ERROR"] == []


@pytest.mark.parametrize(
    "error,reason",
    [
        (EmbeddingUnavailableError(reason="model_missing"), "model_missing"),
        (EmbeddingUnavailableError(reason="unreachable"), "unreachable"),
        (ConnectionError("offline"), "unreachable"),
        (TimeoutError("timeout"), "unreachable"),
        (httpx.ReadTimeout("timeout"), "unreachable"),
    ],
)
def test_rank_embedding_failure_returns_report(
    tmp_path: Path, error: Exception, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    client.failure = error

    result, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", reason)
    assert report.coverage == Coverage(embedded=1, total=1, truncated=0)
    assert len(client.calls) == 1
    assert MODEL in caplog.records[-1].getMessage()
    assert caplog.records[-1].exc_info is not None


def test_rank_bad_query_dimensions_returns_bad_response(tmp_path: Path) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passages = [document(number=0)]
    populate(vectors=vectors, passages=passages, values=[(1.0, 0.0)])
    client.vectors = [[1.0]]

    result, report = dense.rank(course=COURSE, passages=passages, question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", "bad_response")


def test_rank_changed_text_rejects_stale_complete_manifest(tmp_path: Path) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    original = document(number=0)
    populate(vectors=vectors, passages=[original], values=[(1.0, 0.0)])
    before, _ = dense.rank(course=COURSE, passages=[original], question="x")

    result, report = dense.rank(
        course=COURSE, passages=[replace(original, text="edited")], question="x"
    )

    assert before == [original]
    assert (result, report.mode, report.reason) == ([], "bm25", "stale_vectors")
    assert report.coverage == Coverage(embedded=1, total=1, truncated=0)


def test_rank_reuses_matrix_and_invalidates_on_external_commit(tmp_path: Path) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    low, high = document(number=0), document(number=1)
    populate(vectors=vectors, passages=[low, high], values=[(0.6, 0.8), (1.0, 0.0)])
    first, _ = dense.rank(course=COURSE, passages=[low, high], question="x")
    matrices = dense._matrices
    again, _ = dense.rank(course=COURSE, passages=[low, high], question="x")
    assert first == again == [high, low]
    assert dense._matrices is matrices
    writer = VectorStore(path=tmp_path / "vectors.sqlite3")
    populate(vectors=writer, passages=[low, high], values=[(1.0, 0.0), (0.6, 0.8)])

    updated, _ = dense.rank(course=COURSE, passages=[low, high], question="x")

    assert updated == [low, high]
    assert dense._matrices is not matrices


def test_rank_cache_distinguishes_selected_passages(tmp_path: Path) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    first, second = document(number=0), document(number=1)
    populate(vectors=vectors, passages=[first, second], values=[(1.0, 0.0)] * 2)

    all_results, _ = dense.rank(course=COURSE, passages=[first, second], question="x")
    selected, report = dense.rank(course=COURSE, passages=[second], question="x")

    assert all_results == [first, second]
    assert selected == [second]
    assert report.coverage == Coverage(embedded=2, total=2, truncated=0)


def test_rank_manifest_commit_during_read_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dense, vectors, _ = ranker(tmp_path=tmp_path)
    passage = document(number=0)
    populate(vectors=vectors, passages=[passage], values=[(1.0, 0.0)])
    writer = VectorStore(path=tmp_path / "vectors.sqlite3")
    read_coverage = vectors.coverage

    def commit_after_read(*, course: str, model_key: str) -> Coverage:
        coverage = read_coverage(course=course, model_key=model_key)
        writer.sync_units(
            course=course, units={"old": content_hash(passage.text), "new": "missing"}
        )
        return coverage

    monkeypatch.setattr(vectors, "coverage", commit_after_read)
    result, report = dense.rank(course=COURSE, passages=[passage], question="x")

    assert (result, report.mode, report.reason) == ([], "bm25", "partial")
    assert report.coverage == Coverage(embedded=1, total=2, truncated=0)


def test_rank_other_model_has_no_index_and_empty_scope_has_no_hits(
    tmp_path: Path,
) -> None:
    dense, vectors, client = ranker(tmp_path=tmp_path)
    passage = document(number=0)
    populate(vectors=vectors, passages=[passage], values=[(1.0, 0.0)], model="other")
    result, report = dense.rank(course=COURSE, passages=[passage], question="x")
    assert (result, report.reason) == ([], "not_indexed")
    vectors.put_vectors(
        model_key=embedding_model_key(model=MODEL, status=STATUS),
        vectors=[
            StoredVector(text_sha256="unused", vector=(1.0, 0.0), truncated=False)
        ],
    )
    empty, report = dense.rank(course="empty", passages=[], question="x")
    assert (empty, report.reason, report.coverage) == (
        [],
        "not_indexed",
        Coverage(embedded=0, total=0, truncated=0),
    )
    assert client.calls == []
