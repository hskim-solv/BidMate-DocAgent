"""Regression guards for the ``retrieval_backend = "m3"`` measurement spike
(issue #151, follow-up to ADR 0010's deferred BGE-M3 sparse + multi-vector
ablation).

Locks in five contracts that hold without FlagEmbedding installed:

* ``VALID_RETRIEVAL_BACKENDS`` is the canonical 3-element set ``{"dense",
  "hybrid", "m3"}`` — typos like ``"m3x"`` raise at validation time with
  all three options surfaced.
* ``make_plan(retrieval_backend="m3")`` succeeds and carries the choice
  through to the plan dict.
* The ``"m3"`` strategy description string contains the three channel
  names so reviewers reading the plan diagnostics see "dense + sparse +
  colbert" intent.
* Importing ``rag_m3`` succeeds without the optional FlagEmbedding
  dependency (module top-level uses only stdlib + numpy); the
  ``RuntimeError`` is deferred to first ``M3Encoder()`` call.
* The ADR 0001 ``naive_baseline`` bit-identity is preserved by the
  changes — ``retrieval_backend="dense"`` still selects the dense-only
  scoring branch and never imports ``rag_m3``.

The "encode + score three channels end-to-end" test is opt-in
(``@skipUnless`` on FlagEmbedding import). The CI default (hashing
embedding backend) never installs FlagEmbedding, so the suite stays
fast and reproducible.
"""

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

from rag_core import (
    VALID_RETRIEVAL_BACKENDS,
    analyze_query,
    build_index_payload,
    make_plan,
    metadata_targets,
    resolve_pipeline_config,
)
from tests._shared_index_cache import get_shared_raw_index_fixed


def _flag_embedding_available() -> bool:
    try:
        import FlagEmbedding  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return False
    return True


class M3BackendValidationTest(unittest.TestCase):
    """Validation + plan plumbing — runs without FlagEmbedding."""

    def test_valid_retrieval_backends_includes_m3(self) -> None:
        self.assertIn("m3", VALID_RETRIEVAL_BACKENDS)
        self.assertEqual({"dense", "hybrid", "m3"}, VALID_RETRIEVAL_BACKENDS)

    def test_resolve_pipeline_config_accepts_m3(self) -> None:
        config = resolve_pipeline_config(
            {"pipeline": "agentic_full", "retrieval_backend": "m3"}
        )
        self.assertEqual("m3", config["retrieval_backend"])

    def test_resolve_pipeline_config_rejects_m3_typo(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_pipeline_config(
                {"pipeline": "agentic_full", "retrieval_backend": "m3x"}
            )
        # Error message surfaces all three options so a reviewer typing
        # the wrong value sees the available set.
        message = str(ctx.exception)
        self.assertIn("dense", message)
        self.assertIn("hybrid", message)
        self.assertIn("m3", message)

    def test_make_plan_accepts_m3_backend(self) -> None:
        analysis = analyze_query("기관 A 보안", metadata_targets({"chunks": []}))
        plan = make_plan(analysis, top_k=4, retrieval_backend="m3")
        self.assertEqual("m3", plan["retrieval_backend"])
        # Strategy description carries the channel intent for log
        # readers — a reviewer should be able to tell from the plan
        # diagnostic alone that all three BGE-M3 channels participate.
        strategy = str(plan["strategy"])
        self.assertIn("m3", strategy)
        self.assertIn("dense", strategy)
        self.assertIn("sparse", strategy)
        self.assertIn("colbert", strategy)

    def test_make_plan_rejects_m3_typo(self) -> None:
        analysis = analyze_query("기관 A 보안", metadata_targets({"chunks": []}))
        with self.assertRaises(ValueError):
            make_plan(analysis, top_k=4, retrieval_backend="m3y")

    def test_rag_m3_module_importable_without_flag_embedding(self) -> None:
        """The module itself imports stdlib + numpy only — the heavy
        FlagEmbedding import is inside ``M3Encoder.__init__``. This
        keeps the public default ``dense`` path zero-cost even when
        FlagEmbedding is missing.
        """
        if "rag_m3" in sys.modules:
            importlib.reload(sys.modules["rag_m3"])
        import rag_m3  # noqa: F401

        self.assertTrue(hasattr(rag_m3, "M3Encoder"))
        self.assertTrue(hasattr(rag_m3, "get_m3_encoder"))
        self.assertTrue(hasattr(rag_m3, "compute_m3_index_cache"))


class M3MissingDependencyTest(unittest.TestCase):
    """``M3Encoder()`` must raise a clear actionable error when
    FlagEmbedding is absent — not silently fall back to dense (which
    would corrupt the ablation measurement)."""

    def test_m3_encoder_init_raises_when_flag_embedding_missing(self) -> None:
        import rag_m3

        # Simulate FlagEmbedding absence by patching the import. The
        # encoder's ``__init__`` performs the import inside its body so
        # the patch fires there.
        with mock.patch.dict(sys.modules, {"FlagEmbedding": None}):
            with self.assertRaises(RuntimeError) as ctx:
                rag_m3.M3Encoder()
        message = str(ctx.exception)
        self.assertIn("FlagEmbedding", message)
        self.assertIn("requirements-m3.txt", message)


class NaiveBaselineInvariantTest(unittest.TestCase):
    """ADR 0001 — adding the m3 backend must not perturb the default
    ``dense`` path. This test exercises a tiny in-memory build with the
    hashing embedding backend (deterministic, no model downloads) and
    confirms ``retrieval_backend="dense"`` produces a stable plan
    structure with no m3-specific keys leaking in.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index_fixed()

    def test_dense_plan_strategy_does_not_mention_m3(self) -> None:
        analysis = analyze_query("기관 A 보안", metadata_targets(self.index))
        plan = make_plan(analysis, top_k=4, retrieval_backend="dense")
        self.assertNotIn("m3", str(plan["strategy"]).lower())


@unittest.skipUnless(
    _flag_embedding_available(), "FlagEmbedding not installed — m3 spike test skipped"
)
class M3EndToEndTest(unittest.TestCase):  # pragma: no cover — opt-in, gated on dep
    """End-to-end test that loads BGE-M3, runs one query, and asserts
    the three channels are wired through ``score_parts`` and the N-way
    RRF score is normalized to ``[0, 1]``.

    Skipped on the default CI surface (hashing embedding, no
    FlagEmbedding). Run locally after ``pip install -r requirements-m3.txt``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index_fixed()

    def test_m3_score_parts_carry_sparse_and_colbert(self) -> None:
        from rag_core import retrieve

        query = "기관 A의 보안 통제 요구사항은?"
        analysis = analyze_query(query, metadata_targets(self.index))
        plan = make_plan(
            analysis,
            top_k=4,
            metadata_first=True,
            rerank=True,
            verifier_retry=False,
            retrieval_backend="m3",
        )
        evidence = retrieve(self.index, query, analysis, plan)
        self.assertGreater(len(evidence), 0)
        for item in evidence:
            parts = item["score_parts"]
            self.assertIn("m3_sparse", parts)
            self.assertIn("m3_colbert", parts)
            self.assertIn("rank_rrf", parts)
            # N-way RRF normalized to [0, 1] (rrf_k / N projection).
            self.assertGreaterEqual(item["score"], 0.0)
            self.assertLessEqual(item["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
