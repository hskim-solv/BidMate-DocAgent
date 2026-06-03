"""Chroma backend regression for the canonical VectorStore baseline."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rag_core import build_index_payload, run_rag_query
from rag_vector_store import (
    CHROMA_COLLECTION_NAME,
    CHROMA_VECTOR_DIGEST_METADATA_KEY,
    ENV_CHROMA_PATH,
    ENV_INDEX_BACKEND,
    ChromaRankingDriftError,
    ChromaVectorStore,
    InMemoryVectorStore,
    VectorStore,
    _chroma_index_digest,
    _create_chroma_collection,
    _make_chroma_client,
    load_vector_store,
    vector_store_from_matrix,
)


@pytest.fixture
def matrix() -> np.ndarray:
    rng = np.random.default_rng(seed=20260528)
    m = rng.standard_normal((8, 6)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


@pytest.fixture(autouse=True)
def _chroma_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "chroma")
    monkeypatch.delenv(ENV_CHROMA_PATH, raising=False)


def test_chroma_store_basic_shape(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, VectorStore)
    assert isinstance(store, ChromaVectorStore)
    assert store.collection_name.startswith(CHROMA_COLLECTION_NAME)
    assert len(store) == matrix.shape[0]
    assert store.dimension == matrix.shape[1]


def test_chroma_client_disables_telemetry_by_default(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, ChromaVectorStore)
    assert store.client.get_settings().anonymized_telemetry is False


def test_chroma_get_returns_local_matrix_vector(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    for i in range(matrix.shape[0]):
        np.testing.assert_array_equal(store.get(i), matrix[i])


def test_chroma_persist_roundtrip_via_load_vector_store(
    tmp_path: Path,
    matrix: np.ndarray,
) -> None:
    store = vector_store_from_matrix(matrix)
    store.persist(tmp_path)
    restored = load_vector_store(tmp_path, schema_version=2, backend="chroma")
    assert isinstance(restored, ChromaVectorStore)
    assert len(restored) == len(store)
    assert restored.dimension == store.dimension
    for i in range(len(store)):
        np.testing.assert_array_equal(restored.get(i), store.get(i))


def test_memory_sidecar_loads_as_chroma(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_INDEX_BACKEND, "memory")
    memory_store = vector_store_from_matrix(matrix)
    memory_store.persist(tmp_path)

    restored = load_vector_store(tmp_path, schema_version=2, backend="chroma")
    assert isinstance(restored, ChromaVectorStore)
    for i in range(len(memory_store)):
        np.testing.assert_array_equal(restored.get(i), memory_store.get(i))


def test_chroma_empty_matrix_does_not_crash() -> None:
    empty = np.zeros((0, 4), dtype=np.float32)
    store = vector_store_from_matrix(empty)
    assert isinstance(store, ChromaVectorStore)
    assert len(store) == 0
    assert store.query(np.zeros(4, dtype=np.float32), top_k=5) == []


def test_chroma_query_matches_in_memory_top_k_ranking(matrix: np.ndarray) -> None:
    memory_store = InMemoryVectorStore(vectors=matrix)
    chroma_store = vector_store_from_matrix(matrix)

    for i in range(matrix.shape[0]):
        memory_result = memory_store.query(matrix[i], top_k=4)
        chroma_result = chroma_store.query(matrix[i], top_k=4)
        assert [idx for idx, _ in memory_result] == [
            idx for idx, _ in chroma_result
        ], f"index ranking diverged for row {i}"
        for (m_idx, m_score), (c_idx, c_score) in zip(memory_result, chroma_result):
            assert m_idx == c_idx
            assert m_score == pytest.approx(c_score, abs=1e-5)


def test_chroma_query_stable_tie_break(matrix: np.ndarray) -> None:
    twins = matrix.copy()
    twins[3] = twins[1]
    store = vector_store_from_matrix(twins)

    result = store.query(twins[1], top_k=5)
    top_ids = [i for i, score in result if pytest.approx(score, abs=1e-5) == 1.0]
    assert top_ids == sorted(top_ids)


def test_chroma_query_exercises_collection_when_ranking_matches() -> None:
    class MatchingCollection:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def query(
            self,
            *,
            query_embeddings: list[list[float]],
            n_results: int,
            include: list[str],
        ) -> dict[str, list[list[str | float]]]:
            self.calls.append(n_results)
            return {"ids": [["2"]], "distances": [[0.0]]}

    matrix = np.eye(4, dtype=np.float32)
    collection = MatchingCollection()
    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=collection,
    )

    result = store.query(matrix[2], top_k=1)

    assert collection.calls == [1]
    assert result == [(2, 1.0)]


def test_chroma_query_fails_closed_on_ranking_drift() -> None:
    class DriftCollection:
        def query(self, **kwargs: object) -> dict[str, list[list[str | float]]]:
            return {"ids": [["0"]], "distances": [[0.0]]}

    matrix = np.eye(4, dtype=np.float32)
    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=DriftCollection(),
    )

    with pytest.raises(ChromaRankingDriftError, match="Chroma top-k ranking drift"):
        store.query(matrix[2], top_k=1)


def test_chroma_top_k_tie_drift_uses_local_order() -> None:
    matrix = np.eye(4, dtype=np.float32)
    expected = InMemoryVectorStore(vectors=matrix).query(matrix[2], top_k=2)
    alternative = next(idx for idx in [0, 1, 3] if idx != expected[1][0])

    class TieDriftCollection:
        def query(self, **kwargs: object) -> dict[str, list[list[str | float]]]:
            return {
                "ids": [["2", str(alternative)]],
                "distances": [[0.0, 1.0]],
            }

    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=TieDriftCollection(),
    )

    result = store.query(matrix[2], top_k=2)

    assert result == expected


def test_chroma_real_tie_boundary_matches_memory_backend() -> None:
    matrix = np.eye(4, dtype=np.float32)
    memory_store = InMemoryVectorStore(vectors=matrix)
    chroma_store = vector_store_from_matrix(matrix)

    assert chroma_store.query(matrix[2], top_k=2) == memory_store.query(
        matrix[2],
        top_k=2,
    )


def test_chroma_query_uses_collection_for_full_scan() -> None:
    class MatchingCollection:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def query(
            self,
            *,
            query_embeddings: list[list[float]],
            n_results: int,
            include: list[str],
        ) -> dict[str, list[list[str | float]]]:
            self.calls.append(n_results)
            return {
                "ids": [["2", "0", "1", "3"]],
                "distances": [[0.0, 1.0, 1.0, 1.0]],
            }

    matrix = np.eye(4, dtype=np.float32)
    expected = InMemoryVectorStore(vectors=matrix).query(matrix[2], top_k=len(matrix))
    collection = MatchingCollection()
    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=collection,
    )

    result = store.query(matrix[2], top_k=len(matrix))

    assert collection.calls == [len(matrix)]
    assert result == expected


def test_chroma_full_scan_survives_lossy_collection() -> None:
    """Regression for #1841: a full-corpus scan must not crash when chroma's
    in-memory HNSW returns fewer rows than requested. The exact numpy ranking
    is served instead; the lossy collection result is discarded."""

    class LossyCollection:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def query(
            self,
            *,
            query_embeddings: list[list[float]],
            n_results: int,
            include: list[str],
        ) -> dict[str, list[list[str | float]]]:
            self.calls.append(n_results)
            # Drop one row, as HNSW does when n_results ≈ collection size.
            return {"ids": [["2", "0", "1"]], "distances": [[0.0, 1.0, 1.0]]}

    matrix = np.eye(4, dtype=np.float32)
    expected = InMemoryVectorStore(vectors=matrix).query(matrix[2], top_k=len(matrix))
    collection = LossyCollection()
    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=collection,
    )

    result = store.query(matrix[2], top_k=len(matrix))  # must not raise

    assert collection.calls == [len(matrix)]  # chroma still attempted
    assert result == expected  # exact numpy ranking served on shortfall


def test_chroma_partial_top_k_short_result_still_raises() -> None:
    """A short result for a *partial* top-k is a real defect, not HNSW
    boundary noise — keep failing closed there (#1841)."""

    class LossyCollection:
        def query(
            self,
            *,
            query_embeddings: list[list[float]],
            n_results: int,
            include: list[str],
        ) -> dict[str, list[list[str | float]]]:
            return {"ids": [["2"]], "distances": [[0.0]]}  # 1 row for top_k=2

    matrix = np.eye(4, dtype=np.float32)
    store = ChromaVectorStore(
        vectors=matrix,
        client=object(),
        collection=LossyCollection(),
    )

    with pytest.raises(ValueError, match="rows for requested top-k"):
        store.query(matrix[2], top_k=2)


def test_naive_baseline_retrieval_uses_chroma_top_k_query() -> None:
    class SpyCollection:
        def __init__(self, inner: object) -> None:
            self.inner = inner
            self.calls: list[int] = []

        def query(self, **kwargs: object) -> object:
            self.calls.append(int(kwargs["n_results"]))
            return self.inner.query(**kwargs)

    index = build_index_payload(
        Path("eval/fixtures/smoke_rfp/raw"),
        embedding_backend="hashing",
    )
    store = index["_vector_store"]
    assert isinstance(store, ChromaVectorStore)
    spy = SpyCollection(store.collection)
    store.collection = spy

    result = run_rag_query(
        index,
        "기관 A의 보안 통제 요구사항은?",
        pipeline="naive_baseline",
    )

    assert result["diagnostics"]["pipeline"] == "naive_baseline"
    assert spy.calls == [5]
    assert result.get("evidence")


def test_hierarchical_dense_retrieval_does_not_use_child_top_k_shortcut() -> None:
    class SpyCollection:
        def __init__(self, inner: object) -> None:
            self.inner = inner
            self.calls: list[int] = []

        def query(self, **kwargs: object) -> object:
            self.calls.append(int(kwargs["n_results"]))
            return self.inner.query(**kwargs)

    index = build_index_payload(
        Path("eval/fixtures/smoke_rfp/raw"),
        embedding_backend="hashing",
    )
    store = index["_vector_store"]
    assert isinstance(store, ChromaVectorStore)
    spy = SpyCollection(store.collection)
    store.collection = spy

    result = run_rag_query(
        index,
        "기관 A의 보안 통제 요구사항은?",
        pipeline="naive_baseline",
        retrieval_mode="hierarchical",
    )

    assert result["diagnostics"]["retrieval_mode"] == "hierarchical"
    assert spy.calls == [len(store)]
    assert result.get("evidence")


def test_naive_baseline_retrieval_fails_closed_on_chroma_ranking_drift() -> None:
    class DriftCollection:
        def __init__(self, size: int) -> None:
            self.size = size
            self.calls: list[int] = []

        def query(self, **kwargs: object) -> dict[str, list[list[str | float]]]:
            n_results = int(kwargs["n_results"])
            self.calls.append(n_results)
            ids = [str(i) for i in range(min(n_results, self.size))]
            return {"ids": [ids], "distances": [[1.0 for _id in ids]]}

    index = build_index_payload(
        Path("eval/fixtures/smoke_rfp/raw"),
        embedding_backend="hashing",
    )
    store = index["_vector_store"]
    assert isinstance(store, ChromaVectorStore)
    drift = DriftCollection(len(store))
    store.collection = drift

    with pytest.raises(ChromaRankingDriftError, match="Chroma top-k ranking drift"):
        run_rag_query(
            index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="naive_baseline",
        )

    assert drift.calls == [5]


def test_chroma_query_by_indices_uses_local_matrix(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    indices = [6, 1, 3]
    result = store.query_by_indices(matrix[0], indices)
    assert [idx for idx, _ in result] == indices
    expected = matrix[indices] @ matrix[0]
    np.testing.assert_allclose([score for _, score in result], expected, rtol=0, atol=1e-6)


def test_chroma_query_dim_mismatch_raises(matrix: np.ndarray) -> None:
    store = vector_store_from_matrix(matrix)
    with pytest.raises(ValueError, match="dim"):
        store.query(np.zeros(99, dtype=np.float32), top_k=3)


def test_chroma_persistent_path_roundtrip(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CHROMA_PATH, str(tmp_path / "chroma"))
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, ChromaVectorStore)
    assert store.collection.count() == matrix.shape[0]
    assert (
        store.collection.metadata[CHROMA_VECTOR_DIGEST_METADATA_KEY]
        == _chroma_index_digest(matrix)
    )


def test_chroma_persistent_path_second_load_does_not_delete_first_collection(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CHROMA_PATH, str(tmp_path / "chroma"))
    first = vector_store_from_matrix(matrix)
    second = vector_store_from_matrix(matrix)

    assert isinstance(first, ChromaVectorStore)
    assert isinstance(second, ChromaVectorStore)
    assert first.collection_name == second.collection_name
    assert first.collection.count() == matrix.shape[0]
    assert second.collection.count() == matrix.shape[0]
    assert first.query(matrix[0], top_k=3) == second.query(matrix[0], top_k=3)


def test_chroma_persistent_path_repairs_partial_collection(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CHROMA_PATH, str(tmp_path / "chroma"))
    import chromadb

    client = _make_chroma_client(chromadb)
    collection_name = f"{CHROMA_COLLECTION_NAME}_{_chroma_index_digest(matrix)}"
    collection = _create_chroma_collection(client, collection_name)
    collection.add(ids=["0", "1"], embeddings=matrix[:2].tolist())
    assert collection.count() == 2

    restored = vector_store_from_matrix(matrix)

    assert isinstance(restored, ChromaVectorStore)
    assert restored.collection.count() == matrix.shape[0]
    for i in range(matrix.shape[0]):
        np.testing.assert_array_equal(restored.get(i), matrix[i])


def test_chroma_persistent_path_rejects_corrupt_partial_collection(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CHROMA_PATH, str(tmp_path / "chroma"))
    import chromadb

    client = _make_chroma_client(chromadb)
    collection_name = f"{CHROMA_COLLECTION_NAME}_{_chroma_index_digest(matrix)}"
    collection = _create_chroma_collection(client, collection_name)
    altered = matrix.copy()
    altered[1] = matrix[2]
    collection.add(ids=["0", "1"], embeddings=altered[:2].tolist())
    assert collection.count() == 2

    with pytest.raises(ValueError, match="partial row 1"):
        vector_store_from_matrix(matrix)


def test_chroma_persistent_path_rejects_digest_mismatch(
    tmp_path: Path,
    matrix: np.ndarray,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CHROMA_PATH, str(tmp_path / "chroma"))
    import chromadb

    client = _make_chroma_client(chromadb)
    collection_name = f"{CHROMA_COLLECTION_NAME}_{_chroma_index_digest(matrix)}"
    collection = _create_chroma_collection(client, collection_name)
    altered = matrix.copy()
    altered[0] = matrix[1]
    collection.upsert(
        ids=[str(i) for i in range(matrix.shape[0])],
        embeddings=altered.tolist(),
    )

    with pytest.raises(ValueError, match="does not match embeddings sidecar digest"):
        vector_store_from_matrix(matrix)
