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
    ENV_QDRANT_URL,
    QDRANT_COLLECTION_NAME,
    QdrantVectorStore,
    VectorStore,
    _make_qdrant_client,
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


# ---------------------------------------------------------------------------
# Stage 2b: query(qvec, top_k) — Qdrant ANN + parity with brute-force
# ---------------------------------------------------------------------------


def test_qdrant_query_returns_top_k_with_self_at_top(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    result = store.query(matrix[2], top_k=3)
    assert len(result) == 3
    assert result[0][0] == 2
    assert result[0][1] == pytest.approx(1.0, abs=1e-5)
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_qdrant_query_matches_in_memory_top_k_ranking(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parity contract for Stage 2b: on a small in-memory Qdrant
    collection (no HNSW kick-in), the top-k cosine ranking must
    exactly match ``InMemoryVectorStore.query`` — both indices and
    scores. Guards against off-by-one and tie-break drift between
    the two backends."""
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    memory_store = vector_store_from_matrix(matrix)
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    qdrant_store = vector_store_from_matrix(matrix)

    # Try every row as a query — surfaces any per-row asymmetry.
    for i in range(matrix.shape[0]):
        memory_result = memory_store.query(matrix[i], top_k=3)
        qdrant_result = qdrant_store.query(matrix[i], top_k=3)
        assert [idx for idx, _ in memory_result] == [
            idx for idx, _ in qdrant_result
        ], f"index ranking diverged for row {i}"
        for (m_idx, m_score), (q_idx, q_score) in zip(
            memory_result, qdrant_result
        ):
            assert m_idx == q_idx
            assert m_score == pytest.approx(q_score, abs=1e-5)


def test_qdrant_query_clamps_top_k_to_n(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    result = store.query(matrix[0], top_k=100)
    # Qdrant respects the `limit` parameter — it returns N points, not 100.
    assert len(result) == len(store)
    assert {idx for idx, _ in result} == set(range(len(store)))


def test_qdrant_query_empty_store_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    empty = np.zeros((0, 4), dtype=np.float32)
    store = vector_store_from_matrix(empty)
    assert store.query(np.zeros(4, dtype=np.float32), top_k=5) == []


def test_qdrant_query_dim_mismatch_raises(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    store = vector_store_from_matrix(matrix)
    with pytest.raises(ValueError, match="dim"):
        store.query(np.zeros(99, dtype=np.float32), top_k=3)


# ---------------------------------------------------------------------------
# Issue #324: moderate-scale parity lockdown
# ---------------------------------------------------------------------------


@pytest.fixture
def clustered_matrix() -> np.ndarray:
    """200 x 64 L2-normalized matrix with 5 latent clusters; models real
    RFP corpora where chunks naturally group around recurring topics."""
    rng = np.random.default_rng(seed=20260512)
    n_clusters = 5
    n_per_cluster = 40
    dim = 64
    centroids = rng.standard_normal((n_clusters, dim)).astype(np.float32)
    rows = []
    for c in range(n_clusters):
        noise = rng.standard_normal((n_per_cluster, dim)).astype(np.float32)
        rows.append(centroids[c] + 0.3 * noise)
    m = np.concatenate(rows, axis=0)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


@pytest.mark.parametrize("top_k", [5, 10])
def test_qdrant_query_matches_in_memory_at_moderate_scale(
    clustered_matrix: np.ndarray,
    top_k: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #324: on a 200 x 64 clustered matrix, Qdrant ``:memory:``
    top-k ranking and scores must still match ``InMemoryVectorStore``
    exactly, locking the "in-memory Qdrant = exact cosine" assumption
    against silent HNSW activation, distance-metric drift, or upsert /
    point-id misalignment that the 6 x 4 Stage 2b parity test cannot
    surface."""
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    memory_store = vector_store_from_matrix(clustered_matrix)
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    qdrant_store = vector_store_from_matrix(clustered_matrix)

    for qi in range(0, clustered_matrix.shape[0], 10):
        memory_result = memory_store.query(clustered_matrix[qi], top_k=top_k)
        qdrant_result = qdrant_store.query(clustered_matrix[qi], top_k=top_k)
        assert len(memory_result) == top_k
        assert len(qdrant_result) == top_k
        assert [idx for idx, _ in memory_result] == [
            idx for idx, _ in qdrant_result
        ], f"index ranking diverged for query row {qi}, top_k={top_k}"
        for (m_idx, m_score), (q_idx, q_score) in zip(
            memory_result, qdrant_result
        ):
            assert m_idx == q_idx
            assert m_score == pytest.approx(q_score, abs=1e-5)


# ---------------------------------------------------------------------------
# Stage 2d: BIDMATE_QDRANT_URL connection routing (#834)
# ---------------------------------------------------------------------------


class _FakeQdrantClient:
    """Captures constructor kwargs without touching the real qdrant
    client. Used to assert ``_make_qdrant_client`` picks the right
    transport for each ``BIDMATE_QDRANT_URL`` value."""

    instances: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        type(self).instances.append(self.kwargs)


@pytest.fixture(autouse=True)
def _reset_fake_client() -> None:
    _FakeQdrantClient.instances.clear()


def test_make_qdrant_client_uses_memory_when_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_QDRANT_URL, raising=False)
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [{"location": ":memory:"}]


def test_make_qdrant_client_treats_memory_marker_as_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_QDRANT_URL, ":memory:")
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [{"location": ":memory:"}]


def test_make_qdrant_client_treats_blank_as_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_QDRANT_URL, "   ")
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [{"location": ":memory:"}]


def test_make_qdrant_client_routes_http_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_QDRANT_URL, "http://localhost:6333")
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [{"url": "http://localhost:6333"}]


def test_make_qdrant_client_routes_https_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        ENV_QDRANT_URL, "https://qdrant.example.com:6333"
    )
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [
        {"url": "https://qdrant.example.com:6333"}
    ]


def test_make_qdrant_client_treats_other_strings_as_filesystem_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_QDRANT_URL, "/var/lib/qdrant/data")
    _make_qdrant_client(_FakeQdrantClient)
    assert _FakeQdrantClient.instances == [
        {"location": "/var/lib/qdrant/data"}
    ]


def test_qdrant_url_ignored_when_index_backend_is_memory(
    matrix: np.ndarray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0001 baseline preservation. Even with BIDMATE_QDRANT_URL
    pointing at a remote, BIDMATE_INDEX_BACKEND=memory (default) must
    keep the in-memory path — the URL only activates once qdrant is
    opted into."""
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    monkeypatch.setenv(ENV_QDRANT_URL, "http://should-not-be-reached:6333")
    store = vector_store_from_matrix(matrix)
    assert not isinstance(store, QdrantVectorStore)
