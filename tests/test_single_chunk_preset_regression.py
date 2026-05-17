"""Regression guard for the ``single_chunk`` preset (issue #938, ADR 0053).

``single_chunk`` is the "fetch one chunk and answer" distinguishing-power
floor — what a contributor would reach for without retrieval engineering.
The three locked-in contracts:

1. **Preset shape** — ``top_k == 1``, ``metadata_first == False``,
   ``rerank == False``, ``rerank_cross_encoder == False``,
   ``verifier_retry == False``, ``retrieval_backend == "dense"``.
2. **Top-k=1 end-to-end** — exactly one evidence item makes it into
   ``run_rag_query`` output for the answerable smoke query.
3. **No verifier retry** — diagnostics show ``retry_count == 0`` and
   ``filter_stage_attempts`` length == 1 (one pass, no relax).

These contracts protect against future refactors that quietly add
metadata-first / rerank / retry to the preset and erase the
distinguishing-power signal we're measuring.
"""

import unittest
from pathlib import Path

from rag_core import build_index_payload, run_rag_query
from rag_pipeline_presets import PIPELINE_PRESETS


_ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"


class SingleChunkPresetShapeTest(unittest.TestCase):
    """Static checks on the preset dict — no index build required."""

    def test_single_chunk_preset_exists(self) -> None:
        self.assertIn("single_chunk", PIPELINE_PRESETS)

    def test_single_chunk_preset_shape(self) -> None:
        preset = PIPELINE_PRESETS["single_chunk"]
        # The whole point of the floor: top-1, nothing else.
        self.assertEqual(1, preset["top_k"])
        self.assertFalse(preset["metadata_first"])
        self.assertFalse(preset["rerank"])
        self.assertFalse(preset["rerank_cross_encoder"])
        self.assertFalse(preset["verifier_retry"])
        # retrieval_backend stays "dense" — the random_retrieval ablation
        # row in eval/config.yaml is what pairs single_chunk with the
        # ``random`` backend; the preset itself must not.
        self.assertEqual("dense", preset["retrieval_backend"])
        # ADR 0001 invariants — single_chunk shares the naive_baseline
        # prompt + tokenizer so the only knob that varies is ``top_k``.
        self.assertEqual("minimal_grounded_extractive", preset["prompt_profile"])
        self.assertEqual("regex", preset["bm25_tokenizer"])
        self.assertEqual("identity", preset["query_expansion"])


class SingleChunkPresetEndToEndTest(unittest.TestCase):
    """End-to-end smoke: top-k=1, no verifier retry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def test_single_chunk_returns_exactly_one_evidence_item(self) -> None:
        result = run_rag_query(
            self.index, _ANSWERABLE_QUERY, pipeline="single_chunk"
        )
        evidence = result.get("evidence", [])
        self.assertEqual(
            1,
            len(evidence),
            f"single_chunk must enforce top_k=1; got {len(evidence)} items",
        )

    def test_single_chunk_does_not_retry(self) -> None:
        result = run_rag_query(
            self.index, _ANSWERABLE_QUERY, pipeline="single_chunk"
        )
        diagnostics = result.get("diagnostics", {})
        self.assertEqual(
            0,
            diagnostics.get("retry_count"),
            "single_chunk preset disables verifier_retry — retry_count must be 0",
        )
        attempts = diagnostics.get("filter_stage_attempts", [])
        self.assertEqual(
            1,
            len(attempts),
            "single_chunk runs exactly one retrieval pass — no relaxation",
        )


if __name__ == "__main__":
    unittest.main()
