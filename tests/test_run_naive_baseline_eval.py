import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_naive_baseline_eval as nb


class NaiveBaselineEvalWrapperTest(unittest.TestCase):
    def test_select_naive_config_filters_without_mutating_source(self) -> None:
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
        self.assertEqual(2, len(source["ablation_runs"]))

    def test_build_eval_command_delegates_to_existing_runner(self) -> None:
        command = nb.build_eval_command(
            Path("experiments/runs/r/config.naive.yaml"),
            Path("data/index"),
            Path("experiments/runs/r"),
        )

        self.assertEqual("python3", command[0])
        self.assertEqual("eval/run_eval.py", command[1])
        self.assertIn("--config", command)
        self.assertIn("--index_dir", command)
        self.assertIn("--output_dir", command)

    def test_validate_metrics_fails_when_required_metric_missing(self) -> None:
        with self.assertRaisesRegex(ValueError, "metrics.json missing required keys"):
            nb.validate_metrics(
                {
                    "Retrieval metrics": {"Recall@5": 1.0},
                    "Answer/evidence metrics": {},
                    "Operational metrics": {},
                }
            )

    def test_validate_metrics_fails_when_required_metric_null(self) -> None:
        metrics = self._valid_metrics()
        metrics["Retrieval metrics"]["Recall@5"] = None

        with self.assertRaisesRegex(ValueError, "Retrieval metrics.Recall@5"):
            nb.validate_metrics(metrics)

    def test_comparison_retrieval_gap_is_not_double_counted(self) -> None:
        summary = {
            "index_citation_metadata_coverage": {"coverage_reason": "ok"},
            "case_results": [
                {
                    "id": "c1",
                    "query": "Compare A and B requirements",
                    "query_type": "comparison",
                    "hardcase_categories": [],
                    "answerable": True,
                    "chunk_recall_at_5": 0.5,
                    "chunk_recall_at_10": 0.5,
                    "comparison_target_recall": 0.5,
                    "accuracy": 1.0,
                    "groundedness": 1.0,
                    "citation_precision": 1.0,
                    "claim_citation_alignment": 1.0,
                    "abstained": False,
                    "failure_category": None,
                    "answer": "answer",
                }
            ],
        }

        analysis = nb.categorize_failures(summary, metric_errors=[])

        self.assertEqual(
            1,
            analysis["buckets"]["retrieval_failures"]["multi-chunk evidence missing"],
        )
        self.assertEqual(
            1,
            analysis["representative_cases"][0]["labels"].count(
                "retrieval: multi-chunk evidence missing"
            ),
        )

    def test_export_artifacts_writes_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "experiments" / "runs" / "unit_run"
            (run_dir / "failures").mkdir(parents=True)
            report_path = root / "docs" / "evaluation" / "naive_rag_baseline_report.md"
            summary = self._summary_fixture()
            (run_dir / "eval_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False),
                encoding="utf-8",
            )
            (run_dir / "failures" / "naive_baseline.jsonl").write_text(
                json.dumps(
                    {
                        "question_id": "c1",
                        "failure_type": "retrieval_miss",
                        "generated_answer": "missing",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            config = {
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

            result = nb.export_artifacts(
                run_id="unit_run",
                run_dir=run_dir,
                command=["python3", "eval/run_eval.py"],
                config=config,
                report_path=report_path,
            )

            for name in (
                "metrics.json",
                "retrieved_chunks.jsonl",
                "answers.jsonl",
                "failure_cases.jsonl",
                "summary.md",
            ):
                self.assertTrue((run_dir / name).is_file(), name)
            self.assertTrue(report_path.is_file())
            self.assertEqual(
                0.5,
                result["metrics"]["Retrieval metrics"]["Recall@5"],
            )
            self.assertIn("retrieval_failures", result["analysis"]["buckets"])

    @staticmethod
    def _valid_metrics() -> dict:
        return {
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
                "failed_abstention_rate": 0.0,
                "page_metadata_coverage": 1.0,
            },
            "Operational metrics": {
                "total latency ms": 10.0,
                "retrieval latency mean ms": 2.0,
                "generation latency mean ms": 4.0,
                "P50 latency ms": 10.0,
                "P95 latency ms": 20.0,
            },
        }

    @staticmethod
    def _summary_fixture() -> dict:
        return {
            "config": "eval/config.yaml",
            "index_dir": "data/index",
            "num_predictions": 2,
            "chunk_recall_at_5": 0.5,
            "chunk_recall_at_10": 1.0,
            "chunk_mrr_at_5": 0.5,
            "chunk_ndcg_at_5": 0.5,
            "groundedness": 0.5,
            "accuracy": 0.5,
            "citation_precision": 0.5,
            "claim_citation_alignment": 0.5,
            "abstention": 1.0,
            "abstention_outcomes": {
                "correct_refusal": 1,
                "incorrect_answer": 0,
                "boundary_partial": 0,
            },
            "failure_category_counts": {
                "retrieval_miss": 1,
                "citation_or_page_metadata_issue": 0,
                "verifier_false_negative": 0,
                "verifier_false_positive": 0,
                "answer_synthesis_issue": 0,
                "abstention_failure": 0,
                "evaluation_label_issue": 0,
                "parse_or_metadata_issue": 0,
                "unknown": 0,
            },
            "latency": {"p50": 10.0, "p95": 20.0, "mean": 15.0},
            "stage_latency": {
                "retrieve_ms": {"p50": 2.0, "p95": 3.0, "mean": 2.5, "count": 2},
                "answer_generation_ms": {
                    "p50": 4.0,
                    "p95": 5.0,
                    "mean": 4.5,
                    "count": 2,
                },
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
                    "hardcase_categories": [],
                    "answerable": True,
                    "expected_doc_ids": ["doc-a"],
                    "expected_terms": ["보안"],
                    "gold_evidence": [{"doc_id": "doc-a", "chunk_id": "doc-a::1"}],
                    "gold_chunk_ids": ["doc-a::1"],
                    "retrieved_chunks": [{"rank": 1, "chunk_id": "doc-b::1"}],
                    "chunk_recall_at_5": 0.0,
                    "chunk_recall_at_10": 1.0,
                    "chunk_mrr_at_5": 0.0,
                    "chunk_ndcg_at_5": 0.0,
                    "comparison_target_recall": None,
                    "accuracy": 0.0,
                    "groundedness": 0.0,
                    "citation_precision": 0.0,
                    "claim_citation_alignment": 0.0,
                    "abstention": None,
                    "abstained": False,
                    "evidence_doc_ids": [],
                    "answer": "missing",
                    "citation": [],
                    "failure_category": "retrieval_miss",
                    "latency_ms": 10.0,
                },
                {
                    "id": "c2",
                    "query": "없는 요구사항은?",
                    "query_type": "abstention",
                    "hardcase_categories": ["abstention"],
                    "answerable": False,
                    "expected_doc_ids": [],
                    "expected_terms": [],
                    "gold_evidence": [],
                    "gold_chunk_ids": [],
                    "retrieved_chunks": [],
                    "chunk_recall_at_5": None,
                    "chunk_recall_at_10": None,
                    "chunk_mrr_at_5": None,
                    "chunk_ndcg_at_5": None,
                    "accuracy": None,
                    "groundedness": None,
                    "citation_precision": None,
                    "claim_citation_alignment": None,
                    "abstention": 1.0,
                    "abstained": True,
                    "evidence_doc_ids": [],
                    "answer": "",
                    "citation": [],
                    "failure_category": None,
                    "latency_ms": 20.0,
                },
            ],
        }


if __name__ == "__main__":
    unittest.main()
