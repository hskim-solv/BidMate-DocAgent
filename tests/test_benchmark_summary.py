import unittest
from pathlib import Path

from scripts.summarize_benchmark import registry_entry, render_docs

ROOT_DIR = Path(__file__).resolve().parents[1]


class BenchmarkSummaryTest(unittest.TestCase):
    def test_registry_and_docs_preserve_hardcase_aggregate_only(self) -> None:
        manifest = {
            "run_id": "private_hardcase_unit",
            "generated_at": "2026-05-08T00:00:00Z",
            "git_commit": "abc123",
            "git_dirty": False,
            "suite": {
                "id": "private_hardcase_rfp",
                "dataset": {"id": "private_hardcase_rfp_v1"},
            },
            "ablation_suite": {
                "baseline_run": "text_v1_full",
                "primary_run": "visual_v2_full",
            },
            "ablation_flags": {
                "visual_v2_full": {
                    "pipeline": "agentic_full",
                    "top_k": None,
                    "metadata_first": True,
                    "rerank": True,
                    "verifier_retry": True,
                    "retrieval_mode": "hierarchical",
                    "prompt_profile": "private_visual_v2",
                }
            },
            "metrics": {
                "runs": {
                    "visual_v2_full": {
                        "num_predictions": 2,
                        "accuracy": 0.5,
                        "groundedness": 0.5,
                        "citation_precision": 0.25,
                        "citation_grounding": 0.75,
                        "answer_format_compliance": 0.5,
                        "abstention": None,
                        "retry": 0.5,
                        "latency": {"p50": 1.0, "p95": 2.0, "mean": 1.5},
                        "by_hardcase_category": {
                            "table_heavy": {
                                "num_predictions": 1,
                                "accuracy": 0.0,
                                "groundedness": 0.0,
                                "citation_precision": 0.0,
                                "citation_grounding": 0.0,
                                "answer_format_compliance": 0.0,
                                "abstention": None,
                                "retry": 1.0,
                                "latency": {"p50": 2.0, "p95": 2.0, "mean": 2.0},
                            }
                        },
                    }
                }
            },
            "artifacts": {"run_manifest": "artifacts/benchmarks/private/run_manifest.json"},
        }

        entry = registry_entry(manifest)
        docs = render_docs({"schema_version": 1, "entries": [entry]})

        self.assertIn("by_hardcase_category", entry["primary_metrics"])
        self.assertEqual(0.75, entry["primary_metrics"]["citation_grounding"])
        self.assertIn("## Hard-case Slices", docs)
        self.assertIn(
            "| table_heavy | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | N/A | 1.000 |",
            docs,
        )

    def test_private100_fixture_preserves_privacy_metadata_and_comparison(self) -> None:
        private_manifest = self.load_private100_fixture()
        public_entry = registry_entry(
            {
                "run_id": "public_synthetic_unit",
                "generated_at": "2026-05-07T00:00:00Z",
                "git_commit": "public123",
                "git_dirty": False,
                "suite": {
                    "id": "public_synthetic_rfp",
                    "dataset": {
                        "id": "public_synthetic_rfp_v1",
                        "type": "public_synthetic",
                        "privacy": "public_synthetic",
                        "corpus_size": 4,
                        "anonymized": False,
                    },
                },
                "ablation_suite": {"baseline_run": "naive_baseline", "primary_run": "full"},
                "ablation_flags": {
                    "full": {
                        "pipeline": "agentic_full",
                        "top_k": None,
                        "metadata_first": True,
                        "rerank": True,
                        "verifier_retry": True,
                        "retrieval_mode": "flat",
                        "prompt_profile": "structured_grounded_claims",
                    }
                },
                "metrics": {
                    "runs": {
                        "full": {
                            "num_predictions": 26,
                            "accuracy": 1.0,
                            "groundedness": 1.0,
                            "citation_precision": 1.0,
                            "citation_grounding": 1.0,
                            "answer_format_compliance": 1.0,
                            "abstention": 1.0,
                            "retry": 0.231,
                            "latency": {"p50": 1.9, "p95": 3.7, "mean": 2.1},
                        }
                    }
                },
                "artifacts": {"run_manifest": "artifacts/benchmarks/public/run_manifest.json"},
            }
        )

        private_entry = registry_entry(private_manifest)
        docs = render_docs({"schema_version": 1, "entries": [public_entry, private_entry]})

        self.assertEqual(
            {
                "type": "private_rfp_100doc",
                "privacy": "private_aggregate_only",
                "corpus_size": 100,
                "anonymized": True,
                "comparison_group": "public_synthetic_rfp",
            },
            private_entry["dataset"],
        )
        self.assertEqual(100, private_entry["primary_metrics"]["num_predictions"])
        self.assertIn("## Public vs Private Aggregate", docs)
        self.assertIn("| Cases | 26 | 100 | +74.000 |", docs)
        self.assertIn("| Accuracy | 1.000 | 0.810 | -0.190 |", docs)

    def test_registry_and_docs_do_not_copy_private_raw_fields(self) -> None:
        manifest = self.load_private100_fixture()
        manifest["config_snapshot"] = {"private_file_name": "Secret Agency Procurement.pdf"}
        manifest["metrics"]["runs"]["private100_visual_v2_full"]["case_results"] = [
            {
                "id": "private100-case-001",
                "query": "raw private question text",
                "prediction": {"answer": "raw private answer text"},
                "trace": {"evidence": "raw citation snippet"},
            }
        ]

        entry = registry_entry(manifest)
        docs = render_docs({"schema_version": 1, "entries": [entry]})
        combined = repr(entry) + docs
        entry_text = repr(entry)

        self.assertNotIn("Secret Agency Procurement.pdf", combined)
        self.assertNotIn("raw private question text", combined)
        self.assertNotIn("raw private answer text", combined)
        self.assertNotIn("raw citation snippet", combined)
        self.assertNotIn("'case_results'", entry_text)
        self.assertNotIn("'prediction'", entry_text)
        self.assertNotIn("'query'", entry_text)
        self.assertNotIn("'trace'", entry_text)

    def load_private100_fixture(self) -> dict:
        import json

        path = ROOT_DIR / "benchmarks" / "examples" / "private100_aggregate_manifest.example.json"
        return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
