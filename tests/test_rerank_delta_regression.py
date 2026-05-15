"""Regression guards for rerank delta meta (issue #767).

Pins two contracts:

* `rag_retrieval.apply_fusion_and_reranking` writes `pre_rerank_top10`
  and `post_rerank_top10` chunk_id lists into
  `plan["rerank_cross_encoder_meta"]` whenever the cross-encoder rerank
  stage runs.
* `eval.scorers.case.score_case` consumes those lists with the case's
  gold_chunk_ids to compute `rerank_delta_mrr` /
  `rerank_delta_ndcg_at_10`. Both must be `None` (forward-compat) when
  the rerank stage didn't run — preserves naive_baseline / pre-#767
  prediction-dict invariance (ADR 0001).

Stub-backend invariance: with the default `BIDMATE_RERANK_BACKEND=stub`
the post-rerank order is byte-equivalent to the pre-rerank order, so
both delta values must be exactly 0.0 (not None) — the rerank stage
did run, it just didn't reorder. This is the contract that lets the
CI hashing-backend `full_reranker` row stay 0-delta against `full`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.case import score_case  # noqa: E402


_CASE = {
    "id": "test-rerank-001",
    "query_type": "single_doc",
    "answerable": True,
    "expected_doc_ids": ["doc-a"],
    "expected_terms": ["보안"],
    "query": "보안 요구사항",
}


def _minimal_prediction(
    *,
    retrieved_chunk_ids: list[str] | None = None,
    rerank_meta: dict | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    plan: dict = {}
    if rerank_meta is not None:
        plan["rerank_cross_encoder_meta"] = rerank_meta
    return {
        "evidence": evidence or [],
        "answer": {"status": "supported", "claims": [], "summary": ""},
        "diagnostics": {
            "abstained": False,
            "latency_ms": 1.0,
            "retry_count": 0,
            "retrieved_chunk_ids": retrieved_chunk_ids or [],
            "cold_start": False,
        },
        "plan": plan,
        "analysis": {},
    }


class RerankDeltaInScoreCaseTest(unittest.TestCase):
    """`score_case` must emit `rerank_delta_*` keys with correct values."""

    def test_keys_present_when_rerank_meta_absent(self) -> None:
        """Forward-compat: keys exist but are None when no rerank ran."""
        pred = _minimal_prediction(
            retrieved_chunk_ids=["doc-a::c1", "doc-a::c2"],
            evidence=[{"doc_id": "doc-a", "text": "보안"}],
        )
        result = score_case(_CASE, pred, gold_chunk_ids=["doc-a::c1"])
        self.assertIn("rerank_delta_mrr", result)
        self.assertIn("rerank_delta_ndcg_at_10", result)
        self.assertIsNone(result["rerank_delta_mrr"])
        self.assertIsNone(result["rerank_delta_ndcg_at_10"])

    def test_delta_zero_when_rerank_did_not_reorder(self) -> None:
        """Stub backend contract: identical pre/post → delta = 0.0 (not None)."""
        ids = [f"doc-a::c{i}" for i in range(1, 11)]
        pred = _minimal_prediction(
            retrieved_chunk_ids=ids,
            rerank_meta={
                "pre_rerank_top10": ids,
                "post_rerank_top10": ids,
            },
            evidence=[{"doc_id": "doc-a", "text": "보안"}],
        )
        result = score_case(_CASE, pred, gold_chunk_ids=["doc-a::c1"])
        self.assertEqual(result["rerank_delta_mrr"], 0.0)
        self.assertEqual(result["rerank_delta_ndcg_at_10"], 0.0)

    def test_positive_delta_when_rerank_moves_gold_up(self) -> None:
        """If the reranker promotes a gold chunk, delta > 0."""
        pre = [f"doc-a::c{i}" for i in range(1, 11)]
        post = ["doc-a::c5"] + [c for c in pre if c != "doc-a::c5"]
        pred = _minimal_prediction(
            retrieved_chunk_ids=post,
            rerank_meta={
                "pre_rerank_top10": pre,
                "post_rerank_top10": post,
            },
            evidence=[{"doc_id": "doc-a", "text": "보안"}],
        )
        # gold rank: 5 (MRR=0.2) → 1 (MRR=1.0), delta_mrr = +0.8
        result = score_case(_CASE, pred, gold_chunk_ids=["doc-a::c5"])
        self.assertIsNotNone(result["rerank_delta_mrr"])
        self.assertAlmostEqual(result["rerank_delta_mrr"], 0.8, places=4)
        # NDCG@10 also strictly improves when the single gold chunk
        # moves to rank 1.
        self.assertIsNotNone(result["rerank_delta_ndcg_at_10"])
        self.assertGreater(result["rerank_delta_ndcg_at_10"], 0.0)

    def test_negative_delta_when_rerank_demotes_gold(self) -> None:
        """If the reranker demotes a gold chunk, delta < 0."""
        pre = [f"doc-a::c{i}" for i in range(1, 11)]
        # Move c1 (gold) to last position
        post = [c for c in pre if c != "doc-a::c1"] + ["doc-a::c1"]
        pred = _minimal_prediction(
            retrieved_chunk_ids=post,
            rerank_meta={
                "pre_rerank_top10": pre,
                "post_rerank_top10": post,
            },
            evidence=[{"doc_id": "doc-a", "text": "보안"}],
        )
        # gold rank: 1 (MRR=1.0) → 10 (MRR=0.1), delta_mrr = -0.9
        result = score_case(_CASE, pred, gold_chunk_ids=["doc-a::c1"])
        self.assertIsNotNone(result["rerank_delta_mrr"])
        self.assertAlmostEqual(result["rerank_delta_mrr"], -0.9, places=4)

    def test_delta_none_when_no_gold(self) -> None:
        """No gold_chunk_ids → delta values stay None (no signal)."""
        ids = [f"doc-a::c{i}" for i in range(1, 11)]
        pred = _minimal_prediction(
            retrieved_chunk_ids=ids,
            rerank_meta={
                "pre_rerank_top10": ids,
                "post_rerank_top10": ids,
            },
        )
        result = score_case(_CASE, pred, gold_chunk_ids=None)
        self.assertIsNone(result["rerank_delta_mrr"])
        self.assertIsNone(result["rerank_delta_ndcg_at_10"])


class RerankMetaShapeTest(unittest.TestCase):
    """`rag_retrieval` writes pre/post lists when rerank stage runs."""

    def test_apply_fusion_writes_pre_post_top10_when_rerank_enabled(self) -> None:
        """Stub-backend integration: meta dict must include both lists."""
        from rag_retrieval import apply_fusion_and_reranking

        scored = [
            {
                "chunk_id": f"doc-a::c{i}",
                "score": 1.0 - i * 0.01,
                "score_parts": {"dense": 1.0 - i * 0.01},
            }
            for i in range(1, 31)
        ]
        plan = {
            "top_k": 10,
            "rerank_cross_encoder": True,
            "retrieval_backend": "dense",
            "retrieval_mode": "flat",
        }
        index = {"documents": []}
        analysis: dict = {}
        apply_fusion_and_reranking(list(scored), index, "q", analysis, plan)
        meta = plan.get("rerank_cross_encoder_meta") or {}
        self.assertIn("pre_rerank_top10", meta)
        self.assertIn("post_rerank_top10", meta)
        self.assertEqual(len(meta["pre_rerank_top10"]), 10)
        self.assertEqual(len(meta["post_rerank_top10"]), 10)
        # Stub backend = identity, so order must match.
        self.assertEqual(meta["pre_rerank_top10"], meta["post_rerank_top10"])

    def test_no_meta_written_when_rerank_disabled(self) -> None:
        """`rerank_cross_encoder=False` must leave plan untouched (ADR 0001)."""
        from rag_retrieval import apply_fusion_and_reranking

        scored = [
            {
                "chunk_id": "doc-a::c1",
                "score": 0.9,
                "score_parts": {"dense": 0.9},
            }
        ]
        plan = {
            "top_k": 10,
            "rerank_cross_encoder": False,
            "retrieval_backend": "dense",
            "retrieval_mode": "flat",
        }
        apply_fusion_and_reranking(scored, {"documents": []}, "q", {}, plan)
        self.assertNotIn("rerank_cross_encoder_meta", plan)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
