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

from eval.run_eval import (  # noqa: E402
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
