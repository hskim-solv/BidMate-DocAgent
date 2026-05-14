"""Regression tests for by_format aggregate in eval_summary (issue #650 / ADR 0039).

Verifies that:
1. `evaluate_run` attaches `case_source_format` to each result when the index
   contains documents with `metadata.source_format`.
2. `summarize_run` produces a `by_format` dict grouped by source_format.
3. `extract_aggregate` in run_real_eval_delta allows only SAFE_FORMAT_BUCKET_KEYS
   and drops unknown bucket names (fail-closed).
4. No per-case payload (FORBIDDEN_KEYS) appears in the by_format output.
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from eval.run_eval import (
    _build_doc_format_map,
    _case_source_format,
    summarize_run,
)
from scripts.run_real_eval_delta import (
    FORBIDDEN_KEYS,
    SAFE_FORMAT_BUCKET_KEYS,
    extract_aggregate,
)


def _make_index(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"documents": docs}


def _make_result(
    case_id: str,
    expected_doc_ids: list[str],
    case_source_format: str | None = None,
    *,
    accuracy: float | None = 1.0,
    answerable: bool = True,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "query_type": "single_doc",
        "hardcase_categories": [],
        "query": "테스트 쿼리",
        "answerable": answerable,
        "expected_doc_ids": expected_doc_ids,
        "evidence_doc_ids": expected_doc_ids,
        "gold_chunk_ids": [],
        "retrieved_chunk_ids": [],
        "doc_match": True,
        "term_match": True,
        "citation_term_match": True,
        "citation_doc_precision": 1.0,
        "accuracy": accuracy,
        "groundedness": 1.0 if answerable else None,
        "citation_precision": 1.0,
        "citation_grounding": None,
        "citation_grounding_errors": [],
        "claim_citation_alignment": None,
        "claim_citation_errors": [],
        "abstention": None if answerable else 1.0,
        "comparison_target_recall": None,
        "comparison_pool_recall": None,
        "latency_ms": 1.0,
        "retry_count": 0,
        "retry_trigger_reasons": [],
        "last_attempt_verified": None,
        "filter_stage": None,
        "selected_top_k": None,
        "retrieval_budget": {},
        "metadata_ambiguous": False,
        "ambiguity_decision": None,
        "ambiguity_reason": None,
        "metadata_candidate_count": None,
        "cold_start": False,
        "stage_latency": {},
        "attempt_latency": [],
        "chunk_recall_at_5": None,
        "chunk_recall_at_10": None,
        "chunk_mrr": None,
        "chunk_ndcg_at_10": None,
        "citation_page_precision": None,
        "citation_region_precision": None,
        "case_source_format": case_source_format,
    }


class TestBuildDocFormatMap(unittest.TestCase):
    def test_source_format_takes_priority_over_document_type(self) -> None:
        index = _make_index(
            [
                {
                    "doc_id": "doc-hwp",
                    "metadata": {
                        "source_format": "hwp",
                        "document_type": "synthetic_public_sample",
                    },
                },
                {
                    "doc_id": "doc-json",
                    "metadata": {"document_type": "synthetic_public_sample"},
                },
            ]
        )
        fmt_map = _build_doc_format_map(index)
        self.assertEqual(fmt_map["doc-hwp"], "hwp")
        self.assertEqual(fmt_map["doc-json"], "synthetic_public_sample")

    def test_unknown_fallback(self) -> None:
        index = _make_index([{"doc_id": "bare", "metadata": {}}])
        self.assertEqual(_build_doc_format_map(index)["bare"], "unknown")

    def test_empty_index(self) -> None:
        self.assertEqual(_build_doc_format_map({}), {})


class TestCaseSourceFormat(unittest.TestCase):
    def test_returns_first_match(self) -> None:
        fmt_map = {"doc-a": "hwp", "doc-b": "pdf"}
        self.assertEqual(_case_source_format(["doc-a", "doc-b"], fmt_map), "hwp")

    def test_returns_none_for_empty_expected_docs(self) -> None:
        self.assertIsNone(_case_source_format([], {"doc-a": "hwp"}))

    def test_returns_none_for_unknown_doc(self) -> None:
        self.assertIsNone(_case_source_format(["ghost"], {}))


class TestSummarizeRunByFormat(unittest.TestCase):
    def _run_config(self) -> dict[str, Any]:
        return {
            "name": "naive_baseline",
            "pipeline": "naive_baseline",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "retrieval_mode": "flat",
            "retrieval_backend": "dense",
        }

    def test_by_format_grouped_correctly(self) -> None:
        case_results = [
            _make_result("hwp-case-1", ["doc-hwp"], "hwp"),
            _make_result("hwp-case-2", ["doc-hwp"], "hwp"),
            _make_result("json-case", ["doc-json"], "synthetic_public_sample"),
        ]
        summary = summarize_run("naive_baseline", self._run_config(), case_results)
        self.assertIn("by_format", summary)
        self.assertIn("hwp", summary["by_format"])
        self.assertIn("synthetic_public_sample", summary["by_format"])
        self.assertEqual(summary["by_format"]["hwp"]["num_predictions"], 2)
        self.assertEqual(summary["by_format"]["synthetic_public_sample"]["num_predictions"], 1)

    def test_by_format_absent_when_no_source_format(self) -> None:
        case_results = [_make_result("case", ["doc-a"], None)]
        summary = summarize_run("naive_baseline", self._run_config(), case_results)
        self.assertNotIn("by_format", summary)

    def test_no_case_results_in_by_format(self) -> None:
        case_results = [_make_result("hwp-case", ["doc-hwp"], "hwp")]
        summary = summarize_run("naive_baseline", self._run_config(), case_results)
        by_format = summary.get("by_format", {})
        for bucket in by_format.values():
            for forbidden in FORBIDDEN_KEYS:
                self.assertNotIn(forbidden, bucket, f"Forbidden key '{forbidden}' in by_format")


class TestExtractAggregateByFormat(unittest.TestCase):
    def _minimal_summary(self, by_format: dict[str, Any]) -> dict[str, Any]:
        return {
            "num_predictions": 3,
            "accuracy": 1.0,
            "groundedness": 1.0,
            "citation_precision": 1.0,
            "citation_grounding": None,
            "claim_citation_alignment": None,
            "answer_format_compliance": 1.0,
            "abstention": None,
            "retry": 0.0,
            "by_format": by_format,
        }

    def test_allowed_buckets_pass_through(self) -> None:
        summary = self._minimal_summary(
            {
                "hwp": {"num_predictions": 2, "accuracy": 1.0},
                "pdf": {"num_predictions": 1, "accuracy": 0.5},
            }
        )
        out = extract_aggregate(summary)
        self.assertIn("by_format", out)
        self.assertIn("hwp", out["by_format"])
        self.assertIn("pdf", out["by_format"])

    def test_unknown_bucket_dropped_fail_closed(self) -> None:
        summary = self._minimal_summary(
            {
                "hwp": {"num_predictions": 1, "accuracy": 1.0},
                "secret_format": {"num_predictions": 99, "accuracy": 0.0},
            }
        )
        out = extract_aggregate(summary)
        self.assertIn("by_format", out)
        self.assertNotIn("secret_format", out.get("by_format", {}))

    def test_no_forbidden_keys_in_output(self) -> None:
        summary = self._minimal_summary(
            {"hwp": {"num_predictions": 1, "accuracy": 1.0, "case_results": "should_be_dropped"}}
        )
        out = extract_aggregate(summary)

        def _all_keys(d: dict) -> set:
            keys = set(d.keys())
            for v in d.values():
                if isinstance(v, dict):
                    keys |= _all_keys(v)
            return keys

        present = _all_keys(out)
        for forbidden in FORBIDDEN_KEYS:
            self.assertNotIn(
                forbidden,
                present,
                f"Forbidden key '{forbidden}' leaked into aggregate output",
            )

    def test_safe_format_bucket_keys_coverage(self) -> None:
        self.assertIn("hwp", SAFE_FORMAT_BUCKET_KEYS)
        self.assertIn("pdf", SAFE_FORMAT_BUCKET_KEYS)
        self.assertIn("synthetic_public_sample", SAFE_FORMAT_BUCKET_KEYS)


if __name__ == "__main__":
    unittest.main()
