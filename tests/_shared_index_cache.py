"""Worker-local cached hashing-backend index for unittest.TestCase setUpClass.

Issue #915 — 13 test classes (test_answer_contract_snapshot,
test_async_rag_query_regression, test_demo_helpers,
test_followup_entity_injection, test_fuzzy_retrieval,
test_hybrid_retrieval_regression, test_llm_synthesis, test_m3_backend_regression
(2 classes), test_naive_baseline_ranking_invariance, test_observability_tracing,
test_partial_topic_grounding, test_retrieval_loop_regression,
test_single_turn_ambiguity) each call ``build_index_payload(ROOT / "data/raw",
embedding_backend="hashing")`` in ``setUpClass``. That signature is byte-identical
to ``tests/conftest.py::shared_raw_index`` — every call returns the same payload
within a single Python process.

unittest.TestCase cannot consume a pytest fixture via injection, so the conftest
fixture cannot help these classes. Instead we cache the payload at module
scope: the first ``get_shared_raw_index()`` call in a worker process pays the
build cost, subsequent calls (across all 13 classes scheduled to the same xdist
worker) return the same dict.

With ``-n auto --dist loadfile`` the index build is now N-workers × 1 instead of
N-workers × 13 classes (+ a handful of method-level rebuilds elsewhere in the
suite). The cache is intentionally module-global (not session-scoped) so it
survives across class boundaries within a single test file and across files
within a single worker.

The payload is treated as read-only by the calling tests (``cls.index = ...``).
Tests that need a *modified* index (different chunking strategy, different
agency subset, ablation overrides) build their own via
``build_index_payload_from_documents`` and are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from rag_core import build_index_payload

ROOT_DIR = Path(__file__).resolve().parents[1]

_INDEX: dict | None = None
_INDEX_FIXED: dict | None = None


def get_shared_raw_index() -> dict:
    """Return the worker-local cached hashing-backend index, building on first call."""
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index_payload(
            ROOT_DIR / "data" / "raw", embedding_backend="hashing"
        )
    return _INDEX


def get_shared_raw_index_fixed() -> dict:
    """Return the worker-local cached ``hashing + chunking_strategy="fixed"`` index.

    Three test modules (``test_naive_baseline_ranking_invariance``,
    ``test_answer_contract_snapshot``, ``test_m3_backend_regression`` with two
    setUpClass methods) pin the `fixed` chunker for byte-identical golden
    reproducibility (ADR 0001 / 0003). Cached separately from the default
    index because the chunker change yields a different chunk_id distribution.
    """
    global _INDEX_FIXED
    if _INDEX_FIXED is None:
        _INDEX_FIXED = build_index_payload(
            ROOT_DIR / "data" / "raw",
            embedding_backend="hashing",
            chunking_strategy="fixed",
        )
    return _INDEX_FIXED
