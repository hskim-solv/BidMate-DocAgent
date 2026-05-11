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
    vector_store_from_matrix(matrix).persist(tmp_path)
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    with pytest.raises(NotImplementedError, match="#176"):
        load_vector_store(tmp_path, schema_version=2)
