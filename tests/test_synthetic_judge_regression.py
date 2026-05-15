"""Regression tests for the synthetic LLM-judge aggregate (ADR 0012).

These pin the committable aggregate schema and stub-mode determinism
so downstream consumers (README rendering, ablation tables, history
deltas) can rely on stable keys and numeric reproducibility.
"""
from __future__ import annotations

import json
import unittest

from eval.judges.synthetic_judge import judge_synthetic_summary


_AGGREGATE_REQUIRED_KEYS = {
    "schema_version",
    "generated_at",
    "backend",
    "model",
    "n",
    "faithfulness_mean",
    "answer_relevance_mean",
    "grounded_rate",
    "agreement_with_verifier",
    "status_distribution",
    "by_query_type",
}

_SLICE_REQUIRED_KEYS = {
    "n",
    "faithfulness_mean",
    "answer_relevance_mean",
    "grounded_rate",
    "agreement_with_verifier",
    "status_distribution",
}


def _fixture_summary() -> dict:
    """Representative 6-case fixture spanning the public synthetic
    query types (single_doc, comparison, follow_up, abstention)."""
    return {
        "case_results": [
            {
                "id": "single_doc_supported",
                "query_type": "single_doc",
                "query": "q1",
                "answer_status": "supported",
                "answer": {"summary": "s1"},
                "evidence": [{"text": "e1"}],
            },
            {
                "id": "single_doc_partial",
                "query_type": "single_doc",
                "query": "q2",
                "answer_status": "partial",
                "answer": {"summary": "s2"},
                "evidence": [{"text": "e2"}],
            },
            {
                "id": "comparison_supported",
                "query_type": "comparison",
                "query": "q3",
                "answer_status": "supported",
                "answer": {"summary": "s3"},
                "evidence": [{"text": "e3"}],
            },
            {
                "id": "follow_up_supported",
                "query_type": "follow_up",
                "query": "q4",
                "answer_status": "supported",
                "answer": {"summary": "s4"},
                "evidence": [{"text": "e4"}],
            },
            {
                "id": "abstention_insufficient",
                "query_type": "abstention",
                "query": "q5",
                "answer_status": "insufficient",
                "answer": {"summary": ""},
                "evidence": [],
            },
            {
                "id": "abstention_partial",
                "query_type": "abstention",
                "query": "q6",
                "answer_status": "partial",
                "answer": {"summary": "s6"},
                "evidence": [{"text": "e6"}],
            },
        ]
    }


class AggregateSchemaTest(unittest.TestCase):
    def test_aggregate_has_required_top_level_keys(self) -> None:
        _local, agg = judge_synthetic_summary(_fixture_summary(), backend="stub")
        self.assertEqual(_AGGREGATE_REQUIRED_KEYS, set(agg))

    def test_each_query_type_slice_has_required_keys(self) -> None:
        _local, agg = judge_synthetic_summary(_fixture_summary(), backend="stub")
        for qtype, slice_agg in agg["by_query_type"].items():
            self.assertEqual(
                _SLICE_REQUIRED_KEYS, set(slice_agg),
                f"slice {qtype!r} missing keys",
            )

    def test_n_consistent_with_input(self) -> None:
        summary = _fixture_summary()
        _local, agg = judge_synthetic_summary(summary, backend="stub")
        self.assertEqual(agg["n"], len(summary["case_results"]))
        # Slice ns sum to overall n.
        slice_total = sum(s["n"] for s in agg["by_query_type"].values())
        self.assertEqual(slice_total, agg["n"])


class DeterminismTest(unittest.TestCase):
    def _aggregate_excluding_timestamp(self, agg: dict) -> dict:
        return {k: v for k, v in agg.items() if k != "generated_at"}

    def test_stub_aggregate_is_byte_equal_across_runs(self) -> None:
        a1 = judge_synthetic_summary(_fixture_summary(), backend="stub")[1]
        a2 = judge_synthetic_summary(_fixture_summary(), backend="stub")[1]
        self.assertEqual(
            json.dumps(self._aggregate_excluding_timestamp(a1), sort_keys=True),
            json.dumps(self._aggregate_excluding_timestamp(a2), sort_keys=True),
        )

    def test_stub_agreement_with_verifier_is_perfect(self) -> None:
        _local, agg = judge_synthetic_summary(_fixture_summary(), backend="stub")
        # Stub mirrors verifier — agreement must be 1.0.
        self.assertEqual(agg["agreement_with_verifier"], 1.0)
        for slice_agg in agg["by_query_type"].values():
            self.assertEqual(slice_agg["agreement_with_verifier"], 1.0)


class CommitBoundaryTest(unittest.TestCase):
    """Ensure the aggregate stays inside ADR 0005's commit boundary."""

    def test_aggregate_contains_no_raw_query_or_answer_text(self) -> None:
        summary = _fixture_summary()
        _local, agg = judge_synthetic_summary(summary, backend="stub")
        flat = json.dumps(agg, ensure_ascii=False)
        for case in summary["case_results"]:
            self.assertNotIn(str(case["query"]), flat)
            self.assertNotIn(case["id"], flat)
            answer_summary = case["answer"]["summary"] if isinstance(case["answer"], dict) else case["answer"]
            if answer_summary:
                self.assertNotIn(answer_summary, flat)
            for ev in case["evidence"]:
                if ev.get("text"):
                    self.assertNotIn(ev["text"], flat)


if __name__ == "__main__":
    unittest.main()
