import numpy as np
import pytest

from sbobina.dense_math import dense_scores, top_k_cosine


class TestDenseScores:
    def test_cosine_as_dot_product_on_normalized_vectors(self) -> None:
        query = [1.0, 0.0, 0.0]
        unit_vectors = np.array(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.70710678, 0.70710678, 0.0]]
        )

        scores = dense_scores(query_vector=query, unit_vectors=unit_vectors)

        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(0.0)
        assert scores[2] == pytest.approx(0.70710678, abs=1e-6)

    def test_empty_unit_vectors_returns_empty_array(self) -> None:
        unit_vectors = np.zeros((0, 3))

        scores = dense_scores(query_vector=[1.0, 0.0, 0.0], unit_vectors=unit_vectors)

        assert scores.shape == (0,)


def test_top_k_cosine_returns_original_indices_in_descending_score_order() -> None:
    matrix = np.array(
        [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    )
    query = np.array([0.8, 0.6, 0.0])

    assert top_k_cosine(matrix=matrix, query=query, k=3, floor=None) == [
        (1, 0.8),
        (0, 0.6),
        (3, 0.0),
    ]


def test_top_k_cosine_floor_keeps_boundary_and_excludes_lower_scores() -> None:
    matrix = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    query = np.array([0.8, 0.6, 0.0])

    assert top_k_cosine(matrix=matrix, query=query, k=3, floor=0.6) == [
        (0, 0.8),
        (1, 0.6),
    ]
    assert top_k_cosine(matrix=matrix, query=query, k=3, floor=None) == [
        (0, 0.8),
        (1, 0.6),
        (2, 0.0),
    ]


def test_top_k_cosine_empty_matrix_returns_empty() -> None:
    matrix = np.zeros((0, 3))
    query = np.array([1.0, 0.0, 0.0])

    assert top_k_cosine(matrix=matrix, query=query, k=3, floor=None) == []


def test_top_k_cosine_k_above_row_count_returns_all_rows_sorted() -> None:
    matrix = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    query = np.array([0.8, 0.6, 0.0])

    assert top_k_cosine(matrix=matrix, query=query, k=10, floor=None) == [
        (1, 0.8),
        (0, 0.6),
    ]


def test_top_k_cosine_ties_keep_lower_index_first() -> None:
    matrix = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    query = np.array([1.0, 0.0, 0.0])

    assert top_k_cosine(matrix=matrix, query=query, k=2, floor=None) == [
        (1, 1.0),
        (2, 1.0),
    ]
