"""Shared pytest fixtures for the tests/ tree (issue #258)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from rag_core import build_index_payload, clear_model_caches


ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def shared_raw_index() -> dict:
    """Hashing-backend index built once per session from data/raw."""
    return build_index_payload(ROOT_DIR / "data" / "raw", embedding_backend="hashing")


@pytest.fixture(scope="session", autouse=True)
def _clear_model_caches_at_session_end() -> Iterator[None]:
    """Drop process-level model caches at session teardown (issue #841).

    RAG senior-review critique #7.2. ``rag_embedding.MODEL_CACHE``
    (and ``visual_ingestion._DONUT_MODEL_CACHE``) accumulate
    SentenceTransformer / Donut model instances across calls. Cached
    instances are stateless after load so individual tests that
    happen to share a key are unaffected — but pytest reruns and
    cross-session resource pressure benefit from a clean slate.

    Session-scope autouse: runs once at the very end of the test
    session. We do NOT clear before each test (per-test clear would
    pay the model load cost on every retrieval test that touches
    embeddings — measured at >5s per load on cold disks). The cache
    survives within a session; only cross-session leakage is closed.
    """
    yield
    clear_model_caches()
