"""Regression guards for the ``QueryParams`` dataclass surface (issue #260).

``run_rag_query`` keeps its pre-#260 positional/keyword signature, with
``params: QueryParams | None`` added as a keyword-only opt-in. These
tests pin three contracts:

1. ``params=QueryParams()`` is byte-identical to the bare positional/keyword
   call — no behavior drift when the bundle path is taken with defaults.
2. ``params=QueryParams(top_k=..., rerank=..., ...)`` yields the same
   stable answer-side fields as the equivalent legacy-kwarg call.
3. Mixing ``params=`` with explicit pipeline kwargs raises ``ValueError``
   so callers can't silently end up with surprising precedence.

Per-call inputs (``context_entities`` / ``conversation_state``) stay
separate kwargs and must still flow through when ``params=`` is set.

The answer dict contract (ADR 0003) is untouched: this PR only bundles
the input pipeline kwargs.
"""
from __future__ import annotations

import unittest
from typing import Any

import pytest

import rag_core
from rag_core import QueryParams, run_rag_query


_QUERY = "기관A의 보안 통제 요구사항은?"


def _stable_subset(result: dict[str, Any]) -> dict[str, Any]:
    """Drop wall-clock + cold-start fields so two warm/cold runs can compare.

    Pins answer, resolved query, evidence identity, and the plan keys that
    are deterministic across runs. Latency, ``cold_start``, and trace
    timestamps are excluded — they vary by wall clock, not by signature.
    """

    plan = result.get("plan") or {}
    return {
        "mode": result.get("mode"),
        "query": result.get("query"),
        "resolved_query": result.get("resolved_query"),
        "answer": result.get("answer"),
        "answer_text": result.get("answer_text"),
        "evidence_ids": [
            (item.get("doc_id"), item.get("chunk_id"))
            for item in result.get("evidence") or []
        ],
        "plan_stable": {
            key: plan.get(key)
            for key in (
                "top_k",
                "rerank",
                "metadata_first",
                "verifier_retry",
                "retrieval_mode",
                "retrieval_backend",
                "candidate_count",
                "total_chunks",
                "filter_fallback_used",
                "rrf_k",
                "bm25_stopword_profile",
            )
        },
    }


class QueryParamsEquivalenceTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _inject_shared_index(self, shared_raw_index: dict[str, Any]) -> None:
        self.index = shared_raw_index

    def setUp(self) -> None:
        # Force cold-start path identical for every test run.
        rag_core._PROCESS_WARM = False

    def test_empty_params_matches_bare_call(self) -> None:
        """``QueryParams()`` must be a no-op equivalent to the bare positional call."""
        rag_core._PROCESS_WARM = False
        legacy = run_rag_query(self.index, _QUERY)
        rag_core._PROCESS_WARM = False
        bundled = run_rag_query(self.index, _QUERY, params=QueryParams())
        self.assertEqual(_stable_subset(legacy), _stable_subset(bundled))

    def test_custom_params_matches_equivalent_legacy_kwargs(self) -> None:
        """Same field values via QueryParams vs explicit kwargs → same result."""
        rag_core._PROCESS_WARM = False
        legacy = run_rag_query(
            self.index,
            _QUERY,
            top_k=3,
            rerank=False,
            retrieval_backend="dense",
        )
        rag_core._PROCESS_WARM = False
        bundled = run_rag_query(
            self.index,
            _QUERY,
            params=QueryParams(top_k=3, rerank=False, retrieval_backend="dense"),
        )
        self.assertEqual(_stable_subset(legacy), _stable_subset(bundled))

    def test_hybrid_retrieval_backend_via_params(self) -> None:
        """Hybrid backend (RRF fusion) honored via params= just like via kwarg."""
        rag_core._PROCESS_WARM = False
        legacy = run_rag_query(
            self.index,
            _QUERY,
            retrieval_backend="hybrid",
            rrf_k=60,
        )
        rag_core._PROCESS_WARM = False
        bundled = run_rag_query(
            self.index,
            _QUERY,
            params=QueryParams(retrieval_backend="hybrid", rrf_k=60),
        )
        self.assertEqual(_stable_subset(legacy), _stable_subset(bundled))

    def test_mixing_params_with_explicit_pipeline_kwarg_raises(self) -> None:
        """Surface the bug: caller can't pass both at once."""
        with self.assertRaises(ValueError) as ctx:
            run_rag_query(
                self.index,
                _QUERY,
                top_k=5,
                params=QueryParams(rerank=False),
            )
        message = str(ctx.exception)
        self.assertIn("params=", message)
        self.assertIn("top_k", message)

    def test_mixing_params_with_explicit_comparison_balance_raises(self) -> None:
        """Same conflict guard for dict-valued kwargs."""
        with self.assertRaises(ValueError) as ctx:
            run_rag_query(
                self.index,
                _QUERY,
                comparison_balance={"enabled": True},
                params=QueryParams(),
            )
        self.assertIn("comparison_balance", str(ctx.exception))

    def test_per_call_kwargs_remain_separate_from_params(self) -> None:
        """``context_entities`` / ``conversation_state`` are per-turn data,
        not pipeline config — they must keep flowing when ``params=`` is set."""
        rag_core._PROCESS_WARM = False
        result = run_rag_query(
            self.index,
            _QUERY,
            context_entities=["기관A"],
            conversation_state=None,
            params=QueryParams(top_k=3),
        )
        self.assertEqual(result["mode"], "rag")
        # conversation_state always echoed back in the return dict.
        self.assertIn("conversation_state", result)


class QueryParamsShapeTest(unittest.TestCase):
    def test_query_params_is_frozen(self) -> None:
        params = QueryParams(top_k=5)
        with self.assertRaises(Exception):
            params.top_k = 10  # type: ignore[misc]

    def test_query_params_defaults_are_none(self) -> None:
        params = QueryParams()
        for field_name in (
            "top_k",
            "metadata_first",
            "rerank",
            "verifier_retry",
            "retrieval_mode",
            "retrieval_backend",
            "pipeline",
            "prompt_profile",
            "comparison_balance",
            "rrf_k",
            "bm25_stopword_profile",
        ):
            self.assertIsNone(
                getattr(params, field_name),
                f"QueryParams.{field_name} default must be None so the empty "
                "bundle is a no-op equivalent to a bare call",
            )

    def test_query_params_is_hashable(self) -> None:
        """frozen + default-only fields → suitable as a dict key / set member."""
        a = QueryParams(top_k=5)
        b = QueryParams(top_k=5)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual({a, b}, {a})


if __name__ == "__main__":
    unittest.main()
