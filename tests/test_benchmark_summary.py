import unittest

from scripts.summarize_benchmark import registry_entry, render_docs


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
        self.assertIn("## Hard-case Slices", docs)
        self.assertIn("| table_heavy | 1 | 0.000 | 0.000 | 0.000 | 0.000 | N/A | 1.000 |", docs)


if __name__ == "__main__":
    unittest.main()
