"""Regression guard for naive-baseline smoke headline metric honesty (#1424).

The smoke wrapper (``scripts/run_naive_baseline_eval.py``) must surface
rule-based headline metric names, not semantic-judge vocabulary
(``Faithfulness`` / ``Answer relevancy`` / ``Citation accuracy``), and must
expose the ``failed_abstention_rate`` and ``page_metadata_coverage``
diagnostics as headline keys. This is a name-only honesty change: ADR 0001
ranking/answer computation is untouched (values still come from
``groundedness`` / ``accuracy`` / ``citation_precision`` / ``abstention`` /
``index_citation_metadata_coverage``), only the surfaced labels changed.
"""
import copy
import unittest

from scripts import run_naive_baseline_eval as nb


def _summary_with_abstention(abstention_value: float) -> dict:
    """One answerable case + one unanswerable case with a tunable abstention."""
    return {
        "config": "eval/config.yaml",
        "index_dir": "data/index",
        "num_predictions": 2,
        "chunk_recall_at_5": 1.0,
        "chunk_recall_at_10": 1.0,
        "chunk_mrr_at_5": 1.0,
        "chunk_ndcg_at_5": 1.0,
        "groundedness": 0.5,
        "accuracy": 0.5,
        "citation_precision": 0.5,
        "claim_citation_alignment": 0.5,
        "abstention": abstention_value,
        "abstention_outcomes": {
            "correct_refusal": 1,
            "incorrect_answer": 0,
            "boundary_partial": 0,
        },
        "failure_category_counts": {"answer_synthesis_issue": 0},
        "latency": {"p50": 10.0, "p95": 20.0, "mean": 15.0},
        "stage_latency": {
            "retrieve_ms": {"p50": 2.0, "p95": 3.0, "mean": 2.5, "count": 2},
            "answer_generation_ms": {"p50": 4.0, "p95": 5.0, "mean": 4.5, "count": 2},
        },
        "index_citation_metadata_coverage": {
            "coverage_reason": "ok",
            "chunks_total": 4,
            "chunks_with_page_span": 4,
            "page_span_coverage": 1.0,
        },
        "case_results": [
            {
                "id": "c1",
                "query": "기관 A의 보안 요구사항은?",
                "query_type": "single_doc",
                "answerable": True,
                "chunk_recall_at_5": 1.0,
                "chunk_recall_at_10": 1.0,
                "chunk_mrr_at_5": 1.0,
                "chunk_ndcg_at_5": 1.0,
                "accuracy": 0.5,
                "groundedness": 0.5,
                "citation_precision": 0.5,
                "claim_citation_alignment": 0.5,
                "abstention": None,
                "answer": "answer",
                "citation": [],
                "failure_category": None,
                "latency_ms": 10.0,
            },
            {
                "id": "c2",
                "query": "없는 요구사항은?",
                "query_type": "abstention",
                "answerable": False,
                "chunk_recall_at_5": None,
                "chunk_recall_at_10": None,
                "chunk_mrr_at_5": None,
                "chunk_ndcg_at_5": None,
                "accuracy": None,
                "groundedness": None,
                "citation_precision": None,
                "claim_citation_alignment": None,
                "abstention": abstention_value,
                "answer": "",
                "citation": [],
                "failure_category": None,
                "latency_ms": 20.0,
            },
        ],
    }


def _config() -> dict:
    return {
        "cases": [
            {
                "id": "c1",
                "answerable": True,
                "expected_doc_ids": ["doc-a"],
                "expected_terms": ["보안"],
            },
            {"id": "c2", "answerable": False},
        ]
    }


def _metrics(summary: dict) -> dict:
    return nb.build_metrics_json(
        summary,
        _config(),
        run_id="reg",
        command=["python3", "eval/run_eval.py"],
        artifact_paths={},
    )


class SmokeMetricSemanticsRegressionTest(unittest.TestCase):
    def test_smoke_headline_uses_rule_based_metric_names(self) -> None:
        block = _metrics(_summary_with_abstention(1.0))["Answer/evidence metrics"]

        self.assertIn("rule_based_groundedness", block)
        self.assertIn("term_coverage_accuracy", block)
        self.assertIn("citation_chunk_accuracy", block)
        self.assertNotIn("Faithfulness", block)
        self.assertNotIn("Answer relevancy", block)
        self.assertNotIn("Citation accuracy", block)

    def test_smoke_surfaces_failed_abstention_rate(self) -> None:
        # answerable=False case with abstention != 1.0 = a failed abstention.
        block = _metrics(_summary_with_abstention(0.0))["Answer/evidence metrics"]

        self.assertIn("failed_abstention_rate", block)
        self.assertGreater(block["failed_abstention_rate"], 0.0)

    def test_smoke_surfaces_page_metadata_coverage(self) -> None:
        summary = _summary_with_abstention(1.0)
        summary["index_citation_metadata_coverage"] = {
            "coverage_reason": "ok",
            "chunks_total": 5,
            "chunks_with_page_span": 4,
            "page_span_coverage": 0.8,
        }

        block = _metrics(summary)["Answer/evidence metrics"]

        self.assertIn("page_metadata_coverage", block)
        self.assertEqual(0.8, block["page_metadata_coverage"])

    def test_validate_metrics_requires_new_keys(self) -> None:
        metrics = {
            "Retrieval metrics": {
                "Recall@5": 1.0,
                "Recall@10": 1.0,
                "MRR@5": 1.0,
                "nDCG@5": 1.0,
            },
            "Answer/evidence metrics": {
                "rule_based_groundedness": 1.0,
                "term_coverage_accuracy": 1.0,
                "citation_chunk_accuracy": 1.0,
                "Hallucination rate": 0.0,
                "Unanswerable detection rate": 1.0,
                # failed_abstention_rate + page_metadata_coverage intentionally omitted
            },
            "Operational metrics": {
                "total latency ms": 10.0,
                "retrieval latency mean ms": 2.0,
                "generation latency mean ms": 4.0,
                "P50 latency ms": 10.0,
                "P95 latency ms": 20.0,
            },
        }

        with self.assertRaisesRegex(ValueError, "metrics.json missing required keys"):
            nb.validate_metrics(metrics)

        # The error names the two newly-required diagnostic keys.
        try:
            nb.validate_metrics(copy.deepcopy(metrics))
        except ValueError as exc:
            message = str(exc)
            self.assertIn("failed_abstention_rate", message)
            self.assertIn("page_metadata_coverage", message)

    def test_naive_baseline_preset_name_unchanged(self) -> None:
        # ADR 0001 lock: the wrapper still selects the naive_baseline preset.
        source = {
            "primary_run": "full",
            "ablation_runs": [
                {"name": "naive_baseline", "pipeline": "naive_baseline"},
                {"name": "full", "pipeline": "agentic_full"},
            ],
            "cases": [{"id": "c1", "query": "q"}],
        }

        filtered = nb.select_naive_config(source)

        self.assertEqual("naive_baseline", filtered["primary_run"])
        self.assertEqual(
            [{"name": "naive_baseline", "pipeline": "naive_baseline"}],
            filtered["ablation_runs"],
        )

    def test_validate_metrics_allows_none_for_diagnostic_keys(self) -> None:
        # HIGH fix (#1424): failed_abstention_rate / page_metadata_coverage
        # return None when not applicable (no unanswerable case; no index
        # page-metadata block). validate_metrics must treat a present key with
        # a None value as valid, not a missing-key error (else export_artifacts
        # crashes on otherwise-fine runs).
        metrics = {
            "Retrieval metrics": {
                "Recall@5": 1.0, "Recall@10": 1.0, "MRR@5": 1.0, "nDCG@5": 1.0,
            },
            "Answer/evidence metrics": {
                "rule_based_groundedness": 1.0,
                "term_coverage_accuracy": 1.0,
                "citation_chunk_accuracy": 1.0,
                "Hallucination rate": 0.0,
                "Unanswerable detection rate": 1.0,
                "failed_abstention_rate": None,
                "page_metadata_coverage": None,
            },
            "Operational metrics": {
                "total latency ms": 10.0,
                "retrieval latency mean ms": 2.0,
                "generation latency mean ms": 4.0,
                "P50 latency ms": 10.0,
                "P95 latency ms": 20.0,
            },
        }

        # Must NOT raise: present key + None value == not-applicable.
        nb.validate_metrics(metrics)

    def test_build_metrics_json_handles_none_diagnostic(self) -> None:
        # End-to-end: a summary with no index page-metadata block yields
        # page_metadata_coverage None and must not crash build_metrics_json
        # (which validates the required key set).
        summary = _summary_with_abstention(1.0)
        summary.pop("index_citation_metadata_coverage", None)

        block = _metrics(summary)["Answer/evidence metrics"]

        self.assertIn("page_metadata_coverage", block)
        self.assertIsNone(block["page_metadata_coverage"])


if __name__ == "__main__":
    unittest.main()
