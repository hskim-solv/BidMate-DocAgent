"""Contract test for the VectorStore abstraction (#232, Stage 1 of #176).

Single test file by design — the heavy lifting (bit-identical ranking
across all dev queries) is done by
``tests/test_naive_baseline_ranking_invariance.py``. This file only
nails down the Protocol surface: shape, round-trip, and the unsupported-
backend rejection path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rag_vector_store import (
    ENV_INDEX_BACKEND,
    InMemoryVectorStore,
    VectorStore,
    load_vector_store,
    vector_store_from_matrix,
)


@pytest.fixture
def matrix() -> np.ndarray:
    rng = np.random.default_rng(seed=20260511)
    m = rng.standard_normal((5, 8)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


def test_in_memory_store_basic_shape(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, VectorStore)
    assert len(store) == 5
    assert store.dimension == 8
    np.testing.assert_array_equal(store.get(2), matrix[2])


def test_in_memory_store_roundtrip(tmp_path: Path, matrix: np.ndarray) -> None:
    original = vector_store_from_matrix(matrix)
    original.persist(tmp_path)
    assert (tmp_path / "embeddings.npy").exists()

    restored = load_vector_store(tmp_path, schema_version=2)
    assert restored is not None
    assert len(restored) == len(original)
    assert restored.dimension == original.dimension
    for i in range(len(original)):
        np.testing.assert_array_equal(restored.get(i), original.get(i))


def test_legacy_schema1_materializes_from_inline_chunks(matrix: np.ndarray) -> None:
    chunks = [{"embedding": matrix[i].tolist()} for i in range(matrix.shape[0])]
    store = load_vector_store(Path("/nonexistent"), schema_version=1, chunks=chunks)
    assert store is not None
    assert len(store) == 5
    np.testing.assert_allclose(store.get(0), matrix[0], rtol=0, atol=1e-6)


def test_unsupported_backend_raises(
    tmp_path: Path, matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``pgvector`` stays Stage 3 (unimplemented); selecting it today
    # must still raise NotImplementedError. ``qdrant`` is now a
    # supported backend (Stage 2a, #176) — see
    # ``tests/test_vector_store_qdrant.py``.
    vector_store_from_matrix(matrix).persist(tmp_path)
    monkeypatch.setenv(ENV_INDEX_BACKEND, "pgvector")
    with pytest.raises(NotImplementedError, match="#176"):
        load_vector_store(tmp_path, schema_version=2)


# ---------------------------------------------------------------------------
# Stage 2b: query(qvec, top_k)
# ---------------------------------------------------------------------------


def test_in_memory_query_returns_top_k_sorted_by_score(matrix: np.ndarray) -> None:
    """Querying with one of the indexed rows must rank that row at idx 0
    with score ≈ 1.0 (self-cosine on an L2-normalized matrix)."""
    store = vector_store_from_matrix(matrix)
    qvec = matrix[2]
    result = store.query(qvec, top_k=3)
    assert len(result) == 3
    assert result[0][0] == 2
    assert pytest.approx(result[0][1], abs=1e-6) == 1.0
    # Scores must be non-increasing.
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_in_memory_query_clamps_top_k_to_n(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    result = store.query(matrix[0], top_k=100)
    assert len(result) == len(store) == 5
    # All five indices are present, no duplicates.
    assert {idx for idx, _ in result} == set(range(5))


def test_in_memory_query_empty_store_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    empty = np.zeros((0, 4), dtype=np.float32)
    store = vector_store_from_matrix(empty)
    assert store.query(np.zeros(4, dtype=np.float32), top_k=5) == []


def test_in_memory_query_top_k_zero_returns_empty(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    assert store.query(matrix[0], top_k=0) == []


def test_in_memory_query_dim_mismatch_raises(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    with pytest.raises(ValueError, match="dim"):
        store.query(np.zeros(99, dtype=np.float32), top_k=3)


# ---------------------------------------------------------------------------
# Issue #795 — query_by_indices(qvec, indices)
# ---------------------------------------------------------------------------


def test_in_memory_query_by_indices_returns_scores_for_subset(
    matrix: np.ndarray,
) -> None:
    """RAG senior-review critique #3 fix: only score the requested
    indices. Output order matches input order, scores match what
    ``self.vectors @ qvec`` would produce."""
    store = vector_store_from_matrix(matrix)
    qvec = matrix[2]
    # Pick a non-monotonic subset to confirm output order tracks input.
    indices = [4, 1, 2]
    result = store.query_by_indices(qvec, indices)
    assert [i for i, _ in result] == indices
    # The score for self (index 2) must be ~1.0; the others are dot
    # products against matrix[2]. Compare to the bulk dot product.
    expected = (matrix[indices] @ qvec).tolist()
    actual = [s for _, s in result]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-6)


def test_in_memory_query_by_indices_empty_indices_returns_empty(
    matrix: np.ndarray,
) -> None:
    store = vector_store_from_matrix(matrix)
    assert store.query_by_indices(matrix[0], []) == []


def test_in_memory_query_by_indices_dim_mismatch_raises(
    matrix: np.ndarray,
) -> None:
    store = vector_store_from_matrix(matrix)
    with pytest.raises(ValueError, match="dim"):
        store.query_by_indices(np.zeros(99, dtype=np.float32), [0, 1])


def test_in_memory_query_by_indices_out_of_range_raises(
    matrix: np.ndarray,
) -> None:
    """The bug we are NOT introducing: out-of-range indices used to
    silently produce zero scores under the old loop. Now they raise
    ``IndexError`` — drift surfaces at the failing call site."""
    store = vector_store_from_matrix(matrix)
    with pytest.raises(IndexError):
        store.query_by_indices(matrix[0], [0, 999])


def test_in_memory_query_by_indices_matches_per_index_get_loop(
    matrix: np.ndarray,
) -> None:
    """Bulk path must agree bit-for-bit with the per-chunk
    ``store.get(idx)`` + dot product loop the old retrieval used."""
    store = vector_store_from_matrix(matrix)
    qvec = matrix[2]
    indices = list(range(len(store)))
    bulk = store.query_by_indices(qvec, indices)
    per_index = [(i, float(np.dot(store.get(i), qvec))) for i in indices]
    assert [i for i, _ in bulk] == [i for i, _ in per_index]
    np.testing.assert_allclose(
        [s for _, s in bulk],
        [s for _, s in per_index],
        rtol=0,
        atol=1e-6,
    )


def test_in_memory_query_stable_tie_break(matrix: np.ndarray) -> None:
    """Two rows with the same score must be returned in ascending
    row-index order — the brute-force loop in ``rag_core.retrieve``
    relies on stable ordering for reproducibility."""
    # Construct a matrix where rows 1 and 3 are identical → identical
    # scores against any query.
    twins = matrix.copy()
    twins[3] = twins[1]
    store = vector_store_from_matrix(twins)
    qvec = twins[1]
    result = store.query(qvec, top_k=5)
    # Rows 1 and 3 both score 1.0; argpartition with stable sort puts
    # the lower index first.
    top_scores = [s for _, s in result if pytest.approx(s, abs=1e-6) == 1.0]
    top_ids = [i for i, s in result if pytest.approx(s, abs=1e-6) == 1.0]
    assert top_scores == sorted(top_scores, reverse=True)
    assert top_ids == sorted(top_ids)
