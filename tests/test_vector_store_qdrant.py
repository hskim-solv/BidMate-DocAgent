"""Qdrant backend regression for the VectorStore abstraction
(#176 Stage 2a).

Tests run only when ``qdrant-client`` is installed
(``pip install qdrant-client``); skipped otherwise. The backend uses
Qdrant's ``location=":memory:"`` mode so no external Qdrant server is
required.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from rag_vector_store import (  # noqa: E402  (after importorskip)
    ENV_INDEX_BACKEND,
    QDRANT_COLLECTION_NAME,
    QdrantVectorStore,
    VectorStore,
    load_vector_store,
    vector_store_from_matrix,
)


@pytest.fixture
def matrix() -> np.ndarray:
    rng = np.random.default_rng(seed=20260512)
    m = rng.standard_normal((6, 4)).astype(np.float32)
    # L2-normalize so the cosine distance on the Qdrant side matches
    # the dot-product ranking the in-memory backend uses.
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


def test_qdrant_store_basic_shape(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, VectorStore)
    assert isinstance(store, QdrantVectorStore)
    assert len(store) == 6
    assert store.dimension == 4


def test_qdrant_get_returns_bit_identical_vector(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 2a invariant: ``get(idx)`` must return the same float32
    row as ``InMemoryVectorStore`` would, so retrieval rankings are
    bit-identical across backends."""
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    for i in range(matrix.shape[0]):
        np.testing.assert_array_equal(store.get(i), matrix[i])


def test_qdrant_collection_holds_matching_point_count(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard against a silent upsert failure — the Qdrant collection
    must hold the same number of points as the matrix."""
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, QdrantVectorStore)
    info = store.client.get_collection(QDRANT_COLLECTION_NAME)
    assert info.points_count == matrix.shape[0]


def test_qdrant_persist_writes_sidecar(
    tmp_path: Path, matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 2a persist still writes ``embeddings.npy`` so users can
    switch backends without rebuilding."""
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    store.persist(tmp_path)
    sidecar = tmp_path / "embeddings.npy"
    assert sidecar.exists()
    np.testing.assert_array_equal(np.load(sidecar), matrix)


def test_qdrant_persist_roundtrip_via_load_vector_store(
    tmp_path: Path, matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``qdrant`` persist + ``qdrant`` load must round-trip
    bit-identical rows."""
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    store.persist(tmp_path)
    restored = load_vector_store(tmp_path, schema_version=2)
    assert isinstance(restored, QdrantVectorStore)
    assert len(restored) == len(store)
    assert restored.dimension == store.dimension
    for i in range(len(store)):
        np.testing.assert_array_equal(restored.get(i), store.get(i))


def test_qdrant_backend_switchable_from_memory_sidecar(
    tmp_path: Path, matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user who built the index with ``memory`` (default) can switch
    to ``qdrant`` on a subsequent load without rebuilding."""
    # Build + persist under the default ``memory`` backend.
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    memory_store = vector_store_from_matrix(matrix)
    memory_store.persist(tmp_path)
    # Now load under ``qdrant`` and expect the same vectors.
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    qdrant_store = load_vector_store(tmp_path, schema_version=2)
    assert isinstance(qdrant_store, QdrantVectorStore)
    for i in range(len(memory_store)):
        np.testing.assert_array_equal(
            qdrant_store.get(i), memory_store.get(i)
        )


def test_qdrant_empty_matrix_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero-chunk indexes are degenerate but legal; the Qdrant
    backend must build a collection with the right dimension and zero
    points instead of raising."""
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    empty = np.zeros((0, 4), dtype=np.float32)
    store = vector_store_from_matrix(empty)
    assert isinstance(store, QdrantVectorStore)
    assert len(store) == 0
