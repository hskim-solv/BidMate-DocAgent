"""Qdrant production server integration test (issue #853).

Drives a real Qdrant HTTP server (typically the
``docker-compose.qdrant.yml`` container on localhost) via the
``BIDMATE_QDRANT_URL`` env var that PR #837 added.  This complements
the in-memory regression suite (``tests/test_vector_store_qdrant.py``):
that file proves the matrix/in-memory adapter math, this file proves
the *network* path actually round-trips.

Tests are guarded by ``@pytest.mark.qdrant_integration`` and an HTTP
liveness probe, so they no-op on machines without Docker / a running
server.  CI does not run them by default; opt in with
``pytest -m qdrant_integration``.

Local workflow::

    make qdrant-up
    make test-qdrant-integration
    make qdrant-down
"""
from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request

import numpy as np
import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from rag_vector_store import (  # noqa: E402  (after importorskip)
    ENV_INDEX_BACKEND,
    ENV_QDRANT_URL,
    QDRANT_COLLECTION_NAME,
    InMemoryVectorStore,
    QdrantVectorStore,
    vector_store_from_matrix,
)


DEFAULT_URL = "http://localhost:6333"
_HEALTH_PATH = "/healthz"


def _server_reachable(url: str, timeout: float = 1.0) -> bool:
    """Probe the Qdrant HTTP server.  Used as the per-test skip gate
    so a missing container produces a clean skip instead of a noisy
    connection error."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + _HEALTH_PATH, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False


_URL = os.environ.get("BIDMATE_QDRANT_INTEGRATION_URL", DEFAULT_URL)
_REACHABLE = _server_reachable(_URL)


pytestmark = [
    pytest.mark.qdrant_integration,
    pytest.mark.skipif(
        not _REACHABLE,
        reason=(
            f"Qdrant server at {_URL} not reachable. "
            "Run `make qdrant-up` (issue #853) before this suite."
        ),
    ),
]


@pytest.fixture
def matrix() -> np.ndarray:
    """L2-normalized (8, 6) matrix — same shape pattern as the
    in-memory regression suite so cosine ranking comparisons are
    straightforward."""
    rng = np.random.default_rng(seed=20260516)
    m = rng.standard_normal((8, 6)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


@pytest.fixture
def qdrant_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Activate the qdrant backend against the integration URL.

    Cleanup happens via ``monkeypatch`` undo, so even a failing test
    leaves no environment leak between tests in the same session.
    """
    monkeypatch.setenv(ENV_INDEX_BACKEND, "qdrant")
    monkeypatch.setenv(ENV_QDRANT_URL, _URL)


def _drop_collection_if_exists() -> None:
    """Best-effort cleanup so back-to-back test runs do not collide
    on point IDs.  Uses qdrant-client directly because the helper
    that creates the collection lives behind the production code
    path under test."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=_URL)
    if client.collection_exists(QDRANT_COLLECTION_NAME):
        client.delete_collection(QDRANT_COLLECTION_NAME)


@pytest.fixture(autouse=True)
def _isolate_collection() -> None:
    _drop_collection_if_exists()
    yield
    _drop_collection_if_exists()


# ---------------------------------------------------------------------------
# Smoke: server-side upsert + query path
# ---------------------------------------------------------------------------


def test_qdrant_http_store_builds_against_real_server(
    matrix: np.ndarray, qdrant_env: None
) -> None:
    store = vector_store_from_matrix(matrix)
    assert isinstance(store, QdrantVectorStore)
    info = store.client.get_collection(QDRANT_COLLECTION_NAME)
    assert info.points_count == matrix.shape[0]
    assert store.dimension == matrix.shape[1]


def test_qdrant_http_get_returns_bit_identical_vector(
    matrix: np.ndarray, qdrant_env: None
) -> None:
    """``get(idx)`` must read from the in-memory matrix, not the
    Qdrant collection — that is the Stage 2a contract.  Verifying it
    against the HTTP path catches accidental client-state coupling."""
    store = vector_store_from_matrix(matrix)
    for i in range(matrix.shape[0]):
        np.testing.assert_array_equal(store.get(i), matrix[i])


def test_qdrant_http_query_returns_top_k_with_self_at_top(
    matrix: np.ndarray, qdrant_env: None
) -> None:
    store = vector_store_from_matrix(matrix)
    result = store.query(matrix[2], top_k=3)
    assert len(result) == 3
    assert result[0][0] == 2
    assert result[0][1] == pytest.approx(1.0, abs=1e-5)
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_qdrant_http_query_matches_in_memory_top_k_ranking(
    matrix: np.ndarray, qdrant_env: None
) -> None:
    """ADR 0001 parity check via the network path.  Both indices and
    scores must match the in-memory backend exactly."""
    memory_store = InMemoryVectorStore(vectors=matrix)
    qdrant_store = vector_store_from_matrix(matrix)

    for i in range(matrix.shape[0]):
        m_result = memory_store.query(matrix[i], top_k=3)
        q_result = qdrant_store.query(matrix[i], top_k=3)
        assert [idx for idx, _ in m_result] == [idx for idx, _ in q_result], (
            f"index ranking diverged via HTTP for row {i}"
        )
        for (m_idx, m_score), (q_idx, q_score) in zip(m_result, q_result):
            assert m_idx == q_idx
            assert m_score == pytest.approx(q_score, abs=1e-5)


def test_qdrant_http_query_by_indices_uses_local_matrix(
    matrix: np.ndarray, qdrant_env: None
) -> None:
    """Per the Protocol docstring + the in-memory test, the
    ``query_by_indices`` path scores via the local matrix dot, not a
    Qdrant round-trip — even on the HTTP backend."""
    store = vector_store_from_matrix(matrix)
    indices = [1, 4, 6]
    result = store.query_by_indices(matrix[0], indices)
    assert [idx for idx, _ in result] == indices  # order preserved
    expected = matrix[indices] @ matrix[0]
    for (_, score), expected_score in zip(result, expected):
        assert score == pytest.approx(float(expected_score), abs=1e-5)
