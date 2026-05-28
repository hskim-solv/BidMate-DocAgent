"""Shared pytest fixtures for the tests/ tree (issue #258)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

# macOS-safe OpenMP defaults. libomp/libgomp read KMP_*/OMP_* at native-library
# load time. torch / sentence_transformers are imported lazily (inside functions
# in rag_embedding.py / visual_ingestion.py), never at module top-level, so this
# conftest import runs before the first native-lib load. Do NOT add a top-level
# `import torch` above this block, and do not re-introduce a pytest re-exec — it
# ran after pytest's fd capture was active, os._exit skipped the capture flush,
# silently discarding all output and hanging xdist runs.
_OPENMP_DEFAULTS = {
    "OMP_NUM_THREADS": "1",
    "KMP_USE_SHM": "FALSE",
    "KMP_INIT_AT_FORK": "FALSE",
}
for _k, _v in _OPENMP_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

import pytest

from rag_core import build_index_payload, clear_model_caches


ROOT_DIR = Path(__file__).resolve().parents[1]
SMOKE_FIXTURE_RAW = ROOT_DIR / "eval" / "fixtures" / "smoke_rfp" / "raw"


@pytest.fixture(scope="session")
def shared_raw_index() -> dict:
    """Hashing-backend index built once per session from eval/fixtures/smoke_rfp/raw."""
    return build_index_payload(SMOKE_FIXTURE_RAW, embedding_backend="hashing")


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
