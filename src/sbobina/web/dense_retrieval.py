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
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore

logger = logging.getLogger(__name__)

NOT_INDEXED = "not_indexed"
PARTIAL = "partial"
STALE_VECTORS = "stale_vectors"
REBUILD_NEEDED = "rebuild_needed"
GPU_BUSY = "gpu_busy"


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
        self, *, course: str, passages: list[RetrievedPassage], question: str,
        arbiter: GpuArbiter | None = None,
    ) -> tuple[list[RetrievedPassage], RetrievalReport]:
        """Rank under whole-course coverage using reconciliation's normalized key.
        ``passages`` are selected document units and complete lecture partitions.
        """
        from sbobina.web.embedding_supervisor import EMBEDDING_STAGE

        version = self._vectors.data_version()
        coverage = self._vectors.coverage(course=course, model_key=self._model_key)
        if arbiter is not None and arbiter.status()[0] == EMBEDDING_STAGE:
            return [], _bm25(reason=GPU_BUSY, coverage=coverage)
        reason = _coverage_reason(
            rebuild_needed=self._vectors.rebuild_needed, coverage=coverage
        )
        if reason is not None:
            return [], _bm25(reason=reason, coverage=coverage)
        matrices = self._load_matrices(passages=passages)
        if matrices is None:
            # A complete manifest can still contain text edited since reindexing.
            return [], _bm25(reason=STALE_VECTORS, coverage=coverage)
        if version != self._vectors.data_version():
            coverage = self._vectors.coverage(course=course, model_key=self._model_key)
            return [], _bm25(reason=PARTIAL, coverage=coverage)
        return self._rank_query(
            matrices=matrices, question=question, coverage=coverage, arbiter=arbiter
        )

    def _rank_query(
        self, matrices: tuple[_DenseList, _DenseList], question: str,
        coverage: Coverage, arbiter: GpuArbiter | None,
    ) -> tuple[list[RetrievedPassage], RetrievalReport]:
        query, reason = self._safe_query_vector(question=question, arbiter=arbiter)
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
        self, question: str, arbiter: GpuArbiter | None
    ) -> tuple[NDArray[np.float64] | None, str | None]:
        """The query vector, or None with the reason the chat falls back to BM25."""
        try:
            return self._leased_query_vector(question=question, arbiter=arbiter), None
        except GpuBusyError:
            return None, GPU_BUSY
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
            # T026 requires BM25 instead of a 500; preserve the unexpected stack.
            logger.exception(
                "Dense query embedding failed unexpectedly: model=%s", self._model
            )
            return None, UNREACHABLE

    def _leased_query_vector(
        self, question: str, arbiter: GpuArbiter | None
    ) -> NDArray[np.float64]:
        from sbobina.web.embedding_supervisor import EMBEDDING_STAGE

        if arbiter is None:
            return self._query_vector(question=question)
        stage, _ = arbiter.status()
        if stage is not None and stage != EMBEDDING_STAGE:
            return self._query_vector(question=question)
        try:
            # T033/R12: a CPU query reloads the GPU instance of the same model.
            # A shared lease prevents indexing from starting during the query.
            with arbiter.chat_turn():
                return self._query_vector(question=question)
        except GpuBusyError as error:
            if error.stage == EMBEDDING_STAGE:
                raise
        # T031: transcription does not contend with the CPU embedding query.
        return self._query_vector(question=question)

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
