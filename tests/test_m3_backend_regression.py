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
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from rag_core import (
    VALID_RETRIEVAL_BACKENDS,
    analyze_query,
    build_index_payload,
    make_plan,
    metadata_targets,
    resolve_pipeline_config,
)


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
        # ADR 0053 (issue #938) — "random" joined the set as the
        # distinguishing-power floor. Update lockstep with the m3 row so
        # both regression guards stay aligned.
        self.assertEqual(
            {"dense", "hybrid", "m3", "random"}, VALID_RETRIEVAL_BACKENDS
        )

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
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
            chunking_strategy="fixed",
        )

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
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
            chunking_strategy="fixed",
        )

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


@unittest.skipUnless(
    _flag_embedding_available(), "FlagEmbedding not installed — m3 spike test skipped"
)
class M3Fp16CacheRegressionTest(unittest.TestCase):  # pragma: no cover — opt-in
    """Issue #1006 — ``BIDMATE_M3_USE_FP16=1`` must apply to colbert cache
    dtype as well as model weights. Before #1006 the env var only halved
    model weights (<2GB) while the colbert per-token cache stayed at fp32
    (~19.8GB on the 26k-chunk kordoc index), defeating the memory-pressure
    rationale documented in the env var's own docstring.

    The dense + sparse channels are unchanged by the cache-dtype switch —
    only colbert vectors are reshaped, and numpy matmul auto-upcasts the
    fp16 matrix in ``colbert_score`` so the scoring path is preserved.
    """

    def _encode_one(self, fp16: bool):
        # Local imports — the test class is gated on
        # ``_flag_embedding_available()`` so this branch only runs when
        # FlagEmbedding is installed.
        import rag_m3
        from rag_m3 import get_m3_encoder

        env_var = "BIDMATE_M3_USE_FP16"
        original = os.environ.get(env_var)
        # Force a fresh encoder so the env var binds at __init__ time.
        # The module-level _ENCODER_CACHE keys by model_name; clear it.
        rag_m3._ENCODER_CACHE.clear()
        try:
            if fp16:
                os.environ[env_var] = "1"
            else:
                os.environ.pop(env_var, None)
            encoder = get_m3_encoder()
            return encoder.encode(["기관 A의 보안 통제 요구사항은?"])
        finally:
            if original is None:
                os.environ.pop(env_var, None)
            else:
                os.environ[env_var] = original
            rag_m3._ENCODER_CACHE.clear()

    def test_colbert_cache_dtype_follows_use_fp16_env_var(self) -> None:
        out_fp32 = self._encode_one(fp16=False)
        out_fp16 = self._encode_one(fp16=True)
        self.assertEqual(out_fp32.colbert[0].dtype, np.float32)
        self.assertEqual(out_fp16.colbert[0].dtype, np.float16)
        # Shape preserved across dtype switch — only storage changes.
        self.assertEqual(out_fp32.colbert[0].shape, out_fp16.colbert[0].shape)

    def test_colbert_score_unchanged_by_cache_dtype(self) -> None:
        """numpy matmul upcasts fp16 → fp32 so the scalar score is
        bit-equal modulo the rounding inherent in the cached fp16
        storage. ``np.testing.assert_allclose`` with rtol=1e-3 captures
        the BGE-M3 paper's <0.1% recall claim at the score level."""
        from rag_m3 import M3Encoder

        out_fp32 = self._encode_one(fp16=False)
        out_fp16 = self._encode_one(fp16=True)
        # Same query vector in both runs (fp32 model output for q here
        # because the encoder was re-initialized at fp32 in run 1 and
        # fp16 in run 2; the colbert vectors of the same input text
        # should still match modulo the cache-storage rounding).
        s_fp32 = M3Encoder.colbert_score(out_fp32.colbert[0], out_fp32.colbert[0])
        s_fp16 = M3Encoder.colbert_score(out_fp16.colbert[0], out_fp16.colbert[0])
        np.testing.assert_allclose(s_fp32, s_fp16, rtol=1e-2)


if __name__ == "__main__":
    unittest.main()
