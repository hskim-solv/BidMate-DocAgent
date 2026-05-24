"""Shared pytest fixtures for the tests/ tree (issue #258)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterator

_OPENMP_DEFAULTS = {
    "OMP_NUM_THREADS": "1",
    "KMP_USE_SHM": "FALSE",
    "KMP_INIT_AT_FORK": "FALSE",
}


def _ensure_openmp_startup_env() -> None:
    """Restart direct pytest runs once with macOS-safe OpenMP defaults.

    Some native runtimes read KMP_* only at process startup. Setting them later
    is too late to prevent libomp SHM/fork aborts in subprocess-heavy tests.
    """
    missing = {
        key: value for key, value in _OPENMP_DEFAULTS.items() if key not in os.environ
    }
    if (
        sys.platform == "darwin"
        and missing
        and os.environ.get("BIDMATE_PYTEST_OPENMP_REEXEC") != "1"
    ):
        env = os.environ.copy()
        env.update(missing)
        env["BIDMATE_PYTEST_OPENMP_REEXEC"] = "1"
        code = subprocess.call(
            [sys.executable, "-m", "pytest", *sys.argv[1:]],
            env=env,
            stdout=sys.__stdout__,
            stderr=sys.__stderr__,
        )
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        os._exit(code)

    for key, value in _OPENMP_DEFAULTS.items():
        os.environ.setdefault(key, value)


_ensure_openmp_startup_env()

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
