import unittest
from pathlib import Path

from eval.run_eval import load_config, summarize_run


ROOT_DIR = Path(__file__).resolve().parents[1]


class EvalMetricsTest(unittest.TestCase):
    def test_summarize_run_groups_metrics_by_hardcase_category(self) -> None:
        case_results = [
            {
                "query_type": "single_doc",
                "hardcase_categories": ["scanned_pdf", "noisy_ocr"],
                "accuracy": 1.0,
                "groundedness": 1.0,
                "citation_precision": 0.5,
                "answer_format_compliance": 1.0,
                "abstention": None,
                "latency_ms": 10.0,
                "retry_count": 1,
                "retry_trigger_reasons": ["topic_not_grounded"],
            },
            {
                "query_type": "single_doc",
                "hardcase_categories": ["scanned_pdf"],
                "accuracy": 0.0,
                "groundedness": 0.0,
                "citation_precision": 0.0,
                "answer_format_compliance": 0.0,
                "abstention": None,
                "latency_ms": 20.0,
                "retry_count": 0,
                "retry_trigger_reasons": [],
            },
        ]

        summary = summarize_run("unit", {"pipeline": "agentic_full"}, case_results)

        self.assertIn("by_hardcase_category", summary)
        self.assertEqual(2, summary["by_hardcase_category"]["scanned_pdf"]["num_predictions"])
        self.assertEqual(0.5, summary["by_hardcase_category"]["scanned_pdf"]["accuracy"])
        self.assertEqual(1, summary["by_hardcase_category"]["noisy_ocr"]["num_predictions"])
        self.assertEqual(1.0, summary["by_hardcase_category"]["noisy_ocr"]["retry"])

    def test_private_hardcase_example_config_loads(self) -> None:
        config = load_config(ROOT_DIR / "eval" / "private_hardcase.example.yaml")

        self.assertEqual("visual_v2_full", config["primary_run"])
        self.assertEqual(
            ["scanned_pdf", "noisy_ocr"],
            config["cases"][0]["hardcase_categories"],
        )


if __name__ == "__main__":
    unittest.main()
