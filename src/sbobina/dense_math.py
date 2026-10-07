from collections.abc import Sequence

import numpy as np


def dense_scores(
    *, query_vector: Sequence[float], unit_vectors: np.ndarray
) -> np.ndarray:
    """Cosine similarity of query_vector against each row of unit_vectors.

    Ollama embeddings are L2-normalized (eval.md § Verifiche su Ollama), so
    cosine reduces to a dot product: no renormalization here.
    """
    if unit_vectors.shape[0] == 0:
        return np.zeros(0)
    return unit_vectors @ np.asarray(query_vector, dtype=np.float64)


def top_k_cosine(
    matrix: np.ndarray, query: np.ndarray, k: int, floor: float | None
) -> list[tuple[int, float]]:
    """Return up to k row indices and cosine scores, with ties ordered by index."""
    scores = dense_scores(query_vector=query.tolist(), unit_vectors=matrix)
    indices = np.argsort(-scores, kind="stable")
    if floor is not None:
        indices = indices[scores[indices] >= floor]
    return [(int(index), float(scores[index])) for index in indices[:k]]
