"""Regression guards for chunk-level retrieval metrics (PR-04).

Pins the behavior of ``derive_gold_chunk_ids``, ``chunk_recall_at_k``,
``chunk_mrr`` and ``chunk_ndcg_at_k`` so future refactors do not silently
break the public ``chunk_retrieval`` aggregate in ``eval_summary.json``.
"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers import (  # noqa: E402
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)
from eval.scorers.chunk_metrics import CHUNK_METRIC_KS
from eval.scorers.case import score_case


class ChunkMetricsTest(unittest.TestCase):
    def test_recall_at_k_basic(self) -> None:
        self.assertEqual(chunk_recall_at_k(["c1", "c2", "c3"], ["c2"], 5), 1.0)
        self.assertEqual(chunk_recall_at_k(["c1", "c2", "c3"], ["c4"], 5), 0.0)
        self.assertEqual(
            chunk_recall_at_k(["c1", "c2", "c3", "c4"], ["c1", "c4"], 2), 0.5
        )

    def test_recall_at_k_returns_none_for_no_gold(self) -> None:
        self.assertIsNone(chunk_recall_at_k(["c1", "c2"], [], 5))

    def test_recall_at_k_returns_zero_for_empty_retrieved(self) -> None:
        self.assertEqual(chunk_recall_at_k([], ["c1"], 5), 0.0)

    def test_mrr_rewards_earlier_hits(self) -> None:
        self.assertEqual(chunk_mrr(["c1", "c2"], ["c1"]), 1.0)
        self.assertEqual(chunk_mrr(["c1", "c2"], ["c2"]), 0.5)
        self.assertEqual(chunk_mrr(["c1", "c2", "c3"], ["c4"]), 0.0)

    def test_mrr_returns_none_for_no_gold(self) -> None:
        self.assertIsNone(chunk_mrr(["c1"], []))

    def test_ndcg_at_k_perfect_when_gold_is_top(self) -> None:
        # 2 gold items, both at top → ideal DCG = actual DCG → 1.0
        score = chunk_ndcg_at_k(["c1", "c2", "c3"], ["c1", "c2"], 10)
        assert score is not None
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_ndcg_at_k_decays_with_lower_position(self) -> None:
        # gold at position 3 → DCG = 1/log2(4) ≈ 0.5 ; IDCG = 1 → ratio ≈ 0.5
        score = chunk_ndcg_at_k(["c1", "c2", "c3"], ["c3"], 10)
        assert score is not None
        self.assertAlmostEqual(score, 1.0 / math.log2(4), places=6)

    def test_ndcg_at_k_returns_none_for_no_gold(self) -> None:
        self.assertIsNone(chunk_ndcg_at_k(["c1", "c2"], [], 10))


class DeriveGoldChunkIdsTest(unittest.TestCase):
    INDEX: dict = {
        "chunks": [
            {"chunk_id": "doc-a::chunk-001", "doc_id": "doc-a", "text": "보안 통제 요구"},
            {"chunk_id": "doc-a::chunk-002", "doc_id": "doc-a", "text": "납기 일정 기준"},
            {"chunk_id": "doc-b::chunk-001", "doc_id": "doc-b", "text": "보안 통제 별도 구성"},
        ]
    }

    def test_derives_from_expected_doc_and_terms(self) -> None:
        case = {
            "expected_doc_ids": ["doc-a"],
            "expected_terms": ["보안 통제"],
        }
        gold = derive_gold_chunk_ids(case, self.INDEX)
        self.assertEqual(gold, ["doc-a::chunk-001"])

    def test_explicit_gold_overrides_derivation(self) -> None:
        case = {
            "gold_chunk_ids": ["override-chunk-001"],
            "expected_doc_ids": ["doc-a"],
            "expected_terms": ["보안 통제"],
        }
        gold = derive_gold_chunk_ids(case, self.INDEX)
        self.assertEqual(gold, ["override-chunk-001"])

    def test_returns_empty_when_no_expectations(self) -> None:
        case = {"answerable": False}
        self.assertEqual(derive_gold_chunk_ids(case, self.INDEX), [])

    def test_returns_empty_for_missing_index(self) -> None:
        case = {"expected_doc_ids": ["doc-a"], "expected_terms": ["보안 통제"]}
        self.assertEqual(derive_gold_chunk_ids(case, None), [])


class ChunkMetricKsConstantTest(unittest.TestCase):
    """Contract test: CHUNK_METRIC_KS must include k=5, k=10, k=20."""

    def test_contains_5_10_20(self) -> None:
        self.assertIn(5, CHUNK_METRIC_KS)
        self.assertIn(10, CHUNK_METRIC_KS)
        self.assertIn(20, CHUNK_METRIC_KS)

    def test_k20_larger_than_k10(self) -> None:
        ks = sorted(CHUNK_METRIC_KS)
        self.assertGreater(ks[-1], ks[-2])  # 20 > 10


def _minimal_prediction(
    retrieved_chunk_ids: list[str] | None = None,
    evidence: list[dict] | None = None,
) -> dict:
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
        "plan": {},
        "analysis": {},
    }


class ScoreCaseChunkMetrics20Test(unittest.TestCase):
    """Integration: score_case must emit chunk_recall_at_20 and chunk_ndcg_at_20."""

    _CASE = {
        "id": "test-001",
        "query_type": "single_doc",
        "answerable": True,
        "expected_doc_ids": ["doc-a"],
        "expected_terms": ["보안"],
        "query": "보안 요구사항",
    }

    def test_chunk_recall_at_20_present_in_output(self) -> None:
        pred = _minimal_prediction(
            retrieved_chunk_ids=["doc-a::chunk-001"],
            evidence=[{"doc_id": "doc-a", "text": "보안 요구사항"}],
        )
        result = score_case(self._CASE, pred, gold_chunk_ids=["doc-a::chunk-001"])
        self.assertIn("chunk_recall_at_20", result)

    def test_chunk_ndcg_at_20_present_in_output(self) -> None:
        pred = _minimal_prediction(
            retrieved_chunk_ids=["doc-a::chunk-001"],
            evidence=[{"doc_id": "doc-a", "text": "보안 요구사항"}],
        )
        result = score_case(self._CASE, pred, gold_chunk_ids=["doc-a::chunk-001"])
        self.assertIn("chunk_ndcg_at_20", result)

    def test_chunk_recall_at_20_is_1_when_gold_in_top20(self) -> None:
        retrieved = [f"doc-a::chunk-{i:03d}" for i in range(1, 22)]  # 21 chunks
        gold_chunk_id = "doc-a::chunk-015"  # rank 15 — within @20 but not @10
        pred = _minimal_prediction(
            retrieved_chunk_ids=retrieved,
            evidence=[{"doc_id": "doc-a", "text": "보안 요구사항"}],
        )
        result = score_case(self._CASE, pred, gold_chunk_ids=[gold_chunk_id])
        self.assertEqual(result["chunk_recall_at_20"], 1.0)
        self.assertEqual(result["chunk_recall_at_10"], 0.0)  # not in @10

    def test_chunk_recall_at_20_none_when_no_gold(self) -> None:
        pred = _minimal_prediction(retrieved_chunk_ids=["doc-a::chunk-001"])
        result = score_case(self._CASE, pred, gold_chunk_ids=None)
        self.assertIsNone(result.get("chunk_recall_at_20"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
