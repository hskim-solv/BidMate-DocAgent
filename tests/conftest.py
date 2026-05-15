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


@pytest.fixture(autouse=True, scope="session")
def _clear_model_caches_at_session_end() -> Iterator[None]:
    """Drop process-level model caches at pytest session teardown.

    Issue #841 — RAG senior-review critique #7.2. ``MODEL_CACHE`` and
    ``visual_ingestion._DONUT_MODEL_CACHE`` accumulate model instances
    across the test session for cost amortization (a cold
    SentenceTransformer load is >5s). We deliberately do NOT clear
    before each test — that would re-pay the load cost on every
    retrieval-touching test. Instead, the cache is dropped once at
    session teardown so cross-session resource pressure (CI runners,
    GPU memory, OS page cache) is not amplified by pytest leaving the
    process warm. Autouse session-scope means every pytest invocation
    inherits the teardown without per-test opt-in.
    """
    yield
    clear_model_caches()
