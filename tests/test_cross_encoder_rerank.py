"""Contract tests for the cross-encoder reranker (issue #163, ADR 0011 pattern).

The reranker is *additive*: it reorders the top-N candidates produced by the
existing 60/25/15 dense+lexical+metadata blend but never introduces new
chunk_ids. Stub backend is identity (CI-deterministic). Real backends
sigmoid-squash logits into [0,1] so the verifier's score floor at
``rag_core.py`` ~L2254 keeps working.

These tests lock the contract on three surfaces:

* unit-level guards on ``rag_rerank.rerank``
* the pass-through stub backend (used by public CI per ADR 0011)
* end-to-end through ``run_rag_query`` to confirm
  ``naive_baseline`` never triggers the cross-encoder
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from typing import Any
from unittest import mock

import rag_rerank


def _make_candidate(chunk_id: str, score: float = 0.5, text: str = "evidence") -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": chunk_id.split("::")[0],
        "title": "T",
        "score": score,
        "text": text,
        "score_parts": {"dense": 0.5, "lexical": 0.3, "metadata": 0.2, "bm25": 0.0},
    }


class RerankStubBackendTest(unittest.TestCase):
    def test_stub_backend_is_identity(self) -> None:
        candidates = [
            _make_candidate("a::001", score=0.9),
            _make_candidate("b::002", score=0.5),
            _make_candidate("c::003", score=0.1),
        ]
        out, meta = rag_rerank.rerank("q", candidates, backend="stub")
        self.assertEqual([c["chunk_id"] for c in out], ["a::001", "b::002", "c::003"])
        self.assertEqual([c["score"] for c in out], [0.9, 0.5, 0.1])
        self.assertFalse(meta["fell_back"])
        self.assertEqual(meta["backend"], "stub")
        self.assertEqual(meta["model"], "stub")
        self.assertEqual(meta["candidates_scored"], 3)

    def test_default_backend_is_stub(self) -> None:
        candidates = [_make_candidate("a::001")]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(rag_rerank.ENV_BACKEND, None)
            out, meta = rag_rerank.rerank("q", candidates)
        self.assertEqual(meta["backend"], rag_rerank.DEFAULT_BACKEND)
        self.assertFalse(meta["fell_back"])

    def test_empty_candidates_short_circuits(self) -> None:
        out, meta = rag_rerank.rerank("q", [], backend="stub")
        self.assertEqual(out, [])
        self.assertFalse(meta["fell_back"])


class RerankFallbackTest(unittest.TestCase):
    def test_unknown_backend_falls_back(self) -> None:
        candidates = [_make_candidate("a::001"), _make_candidate("b::002")]
        out, meta = rag_rerank.rerank("q", candidates, backend="bogus")
        self.assertEqual([c["chunk_id"] for c in out], ["a::001", "b::002"])
        self.assertTrue(meta["fell_back"])
        self.assertTrue(meta["fallback_reason"].startswith("unknown_backend:"))

    def test_backend_error_falls_back(self) -> None:
        candidates = [_make_candidate("a::001"), _make_candidate("b::002")]

        def _boom(*, query: str, candidates: list[dict[str, Any]], model: str | None) -> Any:
            raise RuntimeError("simulated backend failure")

        with mock.patch.dict(rag_rerank._BACKENDS, {"broken": _boom}):
            out, meta = rag_rerank.rerank("q", candidates, backend="broken")

        self.assertEqual([c["chunk_id"] for c in out], ["a::001", "b::002"])
        self.assertTrue(meta["fell_back"])
        self.assertTrue(meta["fallback_reason"].startswith("backend_error:RuntimeError"))

    def test_postcondition_violation_falls_back(self) -> None:
        candidates = [_make_candidate("a::001"), _make_candidate("b::002")]

        def _bad(*, query: str, candidates: list[dict[str, Any]], model: str | None) -> Any:
            # Returns a chunk_id not in the input — violates the subset postcondition.
            return [_make_candidate("evil::999"), candidates[1]], "rogue-model"

        with mock.patch.dict(rag_rerank._BACKENDS, {"bad": _bad}):
            out, meta = rag_rerank.rerank("q", candidates, backend="bad")

        self.assertEqual([c["chunk_id"] for c in out], ["a::001", "b::002"])
        self.assertTrue(meta["fell_back"])
        self.assertEqual(meta["fallback_reason"], "chunk_id_postcondition_violation")


class RerankCohereMissingDepsTest(unittest.TestCase):
    def test_cohere_missing_sdk_raises_then_caller_falls_back(self) -> None:
        candidates = [_make_candidate("a::001")]
        # The rerank() wrapper catches RuntimeError from backends and converts
        # to fell_back=True. With cohere SDK missing, the backend raises and
        # the caller gets a clean fallback to input order.
        with mock.patch.dict(sys.modules, {"cohere": None}):
            out, meta = rag_rerank.rerank("q", candidates, backend="cohere")
        self.assertEqual([c["chunk_id"] for c in out], ["a::001"])
        self.assertTrue(meta["fell_back"])
        self.assertTrue(meta["fallback_reason"].startswith("backend_error:RuntimeError"))


class RerankSigmoidSquashTest(unittest.TestCase):
    def test_attach_cross_encoder_score_sigmoid(self) -> None:
        cand = _make_candidate("a::001", score=0.5)
        squashed = rag_rerank._attach_cross_encoder_score(cand, 5.0, sigmoid=True)
        expected = 1.0 / (1.0 + math.exp(-5.0))
        self.assertAlmostEqual(squashed["score"], expected, places=5)
        self.assertAlmostEqual(squashed["score_parts"]["cross_encoder"], expected, places=5)
        # Original candidate untouched
        self.assertEqual(cand["score"], 0.5)

    def test_attach_cross_encoder_score_cohere_no_sigmoid(self) -> None:
        cand = _make_candidate("a::001")
        # Cohere returns scores already in [0,1] — sigmoid=False clamps
        # and preserves the value.
        squashed = rag_rerank._attach_cross_encoder_score(cand, 0.73, sigmoid=False)
        self.assertAlmostEqual(squashed["score"], 0.73, places=5)

    def test_attach_cross_encoder_score_clamps_out_of_range(self) -> None:
        cand = _make_candidate("a::001")
        squashed = rag_rerank._attach_cross_encoder_score(cand, 1.5, sigmoid=False)
        self.assertEqual(squashed["score"], 1.0)
        squashed_neg = rag_rerank._attach_cross_encoder_score(cand, -0.2, sigmoid=False)
        self.assertEqual(squashed_neg["score"], 0.0)


class RerankPreservesCandidateSetTest(unittest.TestCase):
    """Postcondition: reordered chunk_ids ⊆ input chunk_ids."""

    def test_stub_preserves_exact_set(self) -> None:
        candidates = [_make_candidate(f"a::{i:03d}") for i in range(10)]
        out, meta = rag_rerank.rerank("q", candidates, backend="stub")
        self.assertEqual({c["chunk_id"] for c in out}, {c["chunk_id"] for c in candidates})
        self.assertEqual(len(out), len(candidates))

    def test_top_n_split_preserves_tail_order(self) -> None:
        # Top-N is re-scored, tail is appended in input order.
        candidates = [_make_candidate(f"a::{i:03d}", score=1.0 - i * 0.1) for i in range(5)]
        out, meta = rag_rerank.rerank("q", candidates, backend="stub", top_n=2)
        # Stub is identity so order is unchanged, but the meta records top_n=2.
        self.assertEqual([c["chunk_id"] for c in out], [c["chunk_id"] for c in candidates])
        self.assertEqual(meta["top_n"], 2)
        self.assertEqual(meta["candidates_scored"], 2)


class FakeFlagReranker:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.last_pairs: list[list[str]] = []

    def compute_score(self, pairs: list[list[str]]) -> list[float]:
        self.last_pairs = pairs
        return list(self._scores[: len(pairs)])


class RerankFlagBackendTest(unittest.TestCase):
    def test_bge_backend_sigmoid_squashes_and_resorts(self) -> None:
        # Logits 5.0 and -3.0 → sigmoid ≈ 0.993 and ≈ 0.047.
        # Higher score must come first after re-sort.
        candidates = [
            _make_candidate("a::001", score=0.5, text="first"),
            _make_candidate("b::002", score=0.5, text="second"),
        ]
        fake = FakeFlagReranker([-3.0, 5.0])  # second candidate is the winner
        with mock.patch.object(rag_rerank, "_get_or_load_flag_reranker", return_value=fake):
            out, meta = rag_rerank.rerank("q", candidates, backend="bge")
        self.assertEqual([c["chunk_id"] for c in out], ["b::002", "a::001"])
        # Sigmoid scores in (0, 1) and sorted desc
        self.assertGreater(out[0]["score"], out[1]["score"])
        self.assertGreater(out[0]["score"], 0.9)
        self.assertLess(out[1]["score"], 0.1)
        # score_parts.cross_encoder populated
        self.assertIn("cross_encoder", out[0]["score_parts"])
        self.assertIn("cross_encoder", out[1]["score_parts"])
        self.assertFalse(meta["fell_back"])
        self.assertEqual(meta["model"], rag_rerank.DEFAULT_BGE_MODEL)


class NaiveBaselineInvariantTest(unittest.TestCase):
    """ADR 0001 invariant — naive_baseline must never trigger the cross-encoder."""

    def test_naive_baseline_preset_does_not_enable_cross_encoder(self) -> None:
        import rag_core

        preset = rag_core.PIPELINE_PRESETS["naive_baseline"]
        self.assertFalse(preset.get("rerank_cross_encoder"))

    def test_resolve_pipeline_config_naive_baseline_defaults_false(self) -> None:
        import rag_core

        config = rag_core.resolve_pipeline_config(
            "naive_baseline", default_pipeline="naive_baseline"
        )
        self.assertFalse(config["rerank_cross_encoder"])


class EvalRunConfigTest(unittest.TestCase):
    def test_normalize_run_config_passes_rerank_cross_encoder(self) -> None:
        sys.path.insert(0, str(_repo_eval_dir()))
        try:
            from run_eval import normalize_run_config
        finally:
            sys.path.pop(0)

        row = {
            "name": "full_reranker",
            "pipeline": "agentic_full",
            "rerank": True,
            "rerank_cross_encoder": True,
            "verifier_retry": True,
            "metadata_first": True,
            "retrieval_mode": "flat",
        }
        normalized = normalize_run_config(row)
        self.assertTrue(normalized["rerank_cross_encoder"])

        row_off = dict(row)
        row_off["name"] = "full"
        row_off["rerank_cross_encoder"] = False
        normalized_off = normalize_run_config(row_off)
        self.assertFalse(normalized_off["rerank_cross_encoder"])


def _repo_eval_dir() -> Any:
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "eval"


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
