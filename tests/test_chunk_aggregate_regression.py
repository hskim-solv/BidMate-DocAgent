"""Regression guards for the run-level chunk-metric aggregate in eval_summary.

``score_case`` already emits per-case ``chunk_recall_at_{5,10,20}`` / ``chunk_mrr``
/ ``chunk_ndcg_at_{10,20}`` / ``rerank_delta_*`` (pinned by
``test_chunk_metrics_regression``). This pins the *aggregate* half added by the
measurement-surface PR: ``metric_block`` now folds those per-case values into a
run-level mean + bootstrap CI, skips ``None`` (gold-free) cases instead of
counting them as 0, and always emits every key so each by-slice block keeps a
stable shape for downstream consumers.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import metric_block  # noqa: E402
from eval.scorers.chunk_metrics import CHUNK_METRIC_KS  # noqa: E402

CHUNK_AGG_KEYS = (
    *(f"chunk_recall_at_{k}" for k in CHUNK_METRIC_KS),
    "chunk_mrr",
    "chunk_ndcg_at_10",
    "chunk_ndcg_at_20",
    "rerank_delta_mrr",
    "rerank_delta_ndcg_at_10",
)


def _row(**overrides):
    base = {
        "accuracy": 1.0,
        "groundedness": 1.0,
        "citation_precision": 1.0,
        "abstention": None,
        "query_type": "single_doc",
        "latency_ms": 1.0,
        "retry_count": 0,
    }
    base.update(overrides)
    return base


class ChunkAggregateTest(unittest.TestCase):
    def test_mean_and_ci_emitted(self) -> None:
        rows = [
            _row(
                chunk_recall_at_5=1.0,
                chunk_recall_at_10=1.0,
                chunk_recall_at_20=1.0,
                chunk_mrr=1.0,
                chunk_ndcg_at_10=1.0,
                chunk_ndcg_at_20=1.0,
                rerank_delta_mrr=0.2,
                rerank_delta_ndcg_at_10=0.1,
            ),
            _row(
                chunk_recall_at_5=0.0,
                chunk_recall_at_10=0.0,
                chunk_recall_at_20=0.0,
                chunk_mrr=0.0,
                chunk_ndcg_at_10=0.0,
                chunk_ndcg_at_20=0.0,
                rerank_delta_mrr=0.0,
                rerank_delta_ndcg_at_10=0.0,
            ),
        ]
        block = metric_block(rows)
        self.assertAlmostEqual(block["chunk_recall_at_5"], 0.5)
        self.assertAlmostEqual(block["chunk_mrr"], 0.5)
        self.assertAlmostEqual(block["rerank_delta_mrr"], 0.1)
        for key in CHUNK_AGG_KEYS:
            self.assertIn(key, block)
            self.assertIn(key, block["ci"])
        self.assertEqual(block["ci"]["chunk_recall_at_5"]["n"], 2)

    def test_none_cases_skipped(self) -> None:
        # A gold-free case (chunk metrics None) must not drag the mean toward 0,
        # and an all-None metric must report None mean + None CI (not 0.0).
        rows = [
            _row(
                chunk_recall_at_5=1.0,
                chunk_mrr=1.0,
                chunk_ndcg_at_10=1.0,
                chunk_ndcg_at_20=1.0,
                rerank_delta_mrr=None,
                rerank_delta_ndcg_at_10=None,
            ),
            _row(
                chunk_recall_at_5=None,
                chunk_mrr=None,
                chunk_ndcg_at_10=None,
                chunk_ndcg_at_20=None,
                rerank_delta_mrr=None,
                rerank_delta_ndcg_at_10=None,
            ),
        ]
        block = metric_block(rows)
        self.assertEqual(block["chunk_recall_at_5"], 1.0)
        self.assertEqual(block["ci"]["chunk_recall_at_5"]["n"], 1)
        self.assertIsNone(block["rerank_delta_mrr"])
        self.assertIsNone(block["ci"]["rerank_delta_mrr"])

    def test_keys_present_even_when_rows_lack_metric(self) -> None:
        # Forward-compat: pre-versioning prediction rows carry no chunk keys at
        # all → every aggregate key still appears with a None mean/CI.
        block = metric_block([_row()])
        for key in CHUNK_AGG_KEYS:
            self.assertIn(key, block)
            self.assertIsNone(block[key])
            self.assertIsNone(block["ci"][key])


if __name__ == "__main__":
    unittest.main()
