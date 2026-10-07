import logging
from dataclasses import dataclass
from threading import Lock
from typing import Literal

import httpx
import numpy as np
from numpy.typing import NDArray

from sbobina.dense_math import top_k_cosine
from sbobina.embedding_prompts import embedding_threshold, format_query
from sbobina.embedding_units import content_hash
from sbobina.ollama_embed import (
    UNREACHABLE,
    EmbeddingClient,
    EmbeddingUnavailableError,
    ModelStatus,
    embed_texts,
    validate_dimensions,
)
from sbobina.rank_fusion import fuse_by_rank
from sbobina.retrieval import CANDIDATE_LIMIT, DocumentSource, RetrievedPassage
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore

logger = logging.getLogger(__name__)

NOT_INDEXED = "not_indexed"
PARTIAL = "partial"
STALE_VECTORS = "stale_vectors"
REBUILD_NEEDED = "rebuild_needed"


@dataclass(frozen=True)
class RetrievalReport:
    mode: Literal["dense", "bm25"]
    reason: str | None
    coverage: Coverage | None


@dataclass(frozen=True)
class _DenseList:
    passages: list[RetrievedPassage]
    matrix: NDArray[np.float64]


def _matrix(
    passages: list[RetrievedPassage], vectors: dict[str, StoredVector]
) -> _DenseList:
    return _DenseList(
        passages=passages,
        matrix=np.asarray(
            [vectors[item.passage_id].vector for item in passages], dtype=np.float64
        ),
    )


def _candidates(
    group: _DenseList, query: NDArray[np.float64], floor: float | None
) -> list[tuple[float, RetrievedPassage]]:
    scores = top_k_cosine(
        matrix=group.matrix, query=query, k=CANDIDATE_LIMIT, floor=floor
    )
    return [(-cosine, group.passages[position]) for position, cosine in scores]


class DenseRanker:
    def __init__(
        self,
        *,
        vectors: VectorStore,
        model: str,
        status: ModelStatus,
        client: EmbeddingClient,
    ) -> None:
        # Reconciliation imports course_retrieval; defer this edge to construction.
        from sbobina.web.vector_reconcile import embedding_model_key

        self._vectors = vectors
        self._model = model
        self._status = status
        self._client = client
        self._model_key = embedding_model_key(model=model, status=status)
        self._lock = Lock()
        self._cache_key: tuple[str, int, tuple[RetrievedPassage, ...]] | None = None
        self._matrices: tuple[_DenseList, _DenseList] | None = None

    def rank(
        self, *, course: str, passages: list[RetrievedPassage], question: str
    ) -> tuple[list[RetrievedPassage], RetrievalReport]:
        """Rank current, already partitioned passages under whole-course coverage.

        ``course`` is reconciliation's normalized key, not the registry UUID;
        ``passages`` are selected document units and complete lecture partitions.
        """
        version = self._vectors.data_version()
        coverage = self._vectors.coverage(course=course, model_key=self._model_key)
        reason = _coverage_reason(
            rebuild_needed=self._vectors.rebuild_needed, coverage=coverage
        )
        if reason is not None:
            return [], _bm25(reason=reason, coverage=coverage)
        matrices = self._load_matrices(passages=passages)
        if matrices is None:
            # Full manifest, but a passage's current text hash has no vector
            # (edited since the last reindex): not PARTIAL, which means the
            # course manifest itself is incomplete.
            return [], _bm25(reason=STALE_VECTORS, coverage=coverage)
        if version != self._vectors.data_version():
            coverage = self._vectors.coverage(course=course, model_key=self._model_key)
            return [], _bm25(reason=PARTIAL, coverage=coverage)
        return self._rank_query(matrices=matrices, question=question, coverage=coverage)

    def _rank_query(
        self, matrices: tuple[_DenseList, _DenseList], question: str, coverage: Coverage
    ) -> tuple[list[RetrievedPassage], RetrievalReport]:
        query, reason = self._safe_query_vector(question=question)
        if query is None:
            return [], _bm25(reason=reason or UNREACHABLE, coverage=coverage)
        floor = embedding_threshold(model=self._model)
        rankings = [
            _candidates(group=group, query=query, floor=floor) for group in matrices
        ]
        return fuse_by_rank(rankings=rankings), RetrievalReport(
            mode="dense", reason=None, coverage=coverage
        )

    def _safe_query_vector(
        self, question: str
    ) -> tuple[NDArray[np.float64] | None, str | None]:
        """The query vector, or None with the reason the chat falls back to BM25."""
        try:
            return self._query_vector(question=question), None
        except (EmbeddingUnavailableError, OSError, httpx.HTTPError) as error:
            reason = (
                error.reason
                if isinstance(error, EmbeddingUnavailableError)
                else UNREACHABLE
            )
            logger.warning(
                "Dense query unavailable: model=%s reason=%s",
                self._model,
                reason,
                exc_info=True,
            )
            return None, reason
        except Exception:
            # Any unforeseen embedding failure must degrade to BM25, not raise
            # into the chat turn as a 500 (contract T026); logged with the stack
            # because this path was not anticipated by name.
            logger.exception(
                "Dense query embedding failed unexpectedly: model=%s", self._model
            )
            return None, UNREACHABLE

    def _query_vector(self, question: str) -> NDArray[np.float64]:
        embedded = embed_texts(
            client=self._client,
            model=self._model,
            texts=[format_query(model=self._model, text=question)],
            mode="query",
        )
        validate_dimensions(
            embedded=embedded, expected_dimensions=self._status.dimensions
        )
        return np.asarray(embedded[0].vector, dtype=np.float64)

    def _load_matrices(
        self, passages: list[RetrievedPassage]
    ) -> tuple[_DenseList, _DenseList] | None:
        with self._lock:
            key = (self._model_key, self._vectors.data_version(), tuple(passages))
            if key == self._cache_key:
                return self._matrices
            units = {item.passage_id: content_hash(item.text) for item in passages}
            vectors = self._vectors.vectors_for_units(
                model_key=self._model_key, units=units
            )
            if len(vectors) != len(units):
                return None
            documents = [
                item for item in passages if isinstance(item.source, DocumentSource)
            ]
            lectures = [
                item for item in passages if not isinstance(item.source, DocumentSource)
            ]
            self._matrices = (
                _matrix(passages=documents, vectors=vectors),
                _matrix(passages=lectures, vectors=vectors),
            )
            self._cache_key = key
            return self._matrices


def _coverage_reason(*, rebuild_needed: bool, coverage: Coverage) -> str | None:
    """Why the course cannot be ranked densely yet, or None when it can."""
    if rebuild_needed:
        return REBUILD_NEEDED
    if not coverage.embedded:
        return NOT_INDEXED
    if coverage.embedded < coverage.total:
        return PARTIAL
    return None


def _bm25(*, reason: str, coverage: Coverage) -> RetrievalReport:
    return RetrievalReport(mode="bm25", reason=reason, coverage=coverage)
