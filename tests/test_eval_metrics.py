import unittest
from pathlib import Path

from eval.run_eval import load_config, score_case, summarize_run


ROOT_DIR = Path(__file__).resolve().parents[1]


class EvalMetricsTest(unittest.TestCase):
    def prediction_with_citation(self, citation: dict) -> dict:
        return {
            "answer": {
                "status": "supported",
                "claims": [
                    {
                        "target": "기관 V",
                        "claim": "보안 요구사항은 접근 통제입니다.",
                        "support": "보안 요구사항은 접근 통제입니다.",
                        "citations": [citation],
                    }
                ],
            },
            "answer_text": "보안 요구사항은 접근 통제입니다.",
            "evidence": [
                {
                    "doc_id": "visual-doc",
                    "chunk_id": "visual-doc::chunk-001",
                    "text": "보안 요구사항은 접근 통제입니다.",
                }
            ],
            "diagnostics": {"latency_ms": 1.0, "retry_count": 0},
        }

    def visual_case(self, **overrides: object) -> dict:
        case = {
            "id": "visual-grounding",
            "query_type": "single_doc",
            "query": "기관 V의 보안 요구사항은?",
            "expected_doc_ids": ["visual-doc"],
            "expected_terms": ["보안 요구사항", "접근 통제"],
            "expected_citation_terms": ["보안 요구사항", "접근 통제"],
            "expected_claim_targets": ["기관 V"],
            "expected_citation_pages": [{"doc_id": "visual-doc", "pages": [2]}],
            "expected_citation_regions": [
                {
                    "doc_id": "visual-doc",
                    "page_number": 2,
                    "bbox": [10, 20, 120, 160],
                    "min_iou": 0.9,
                }
            ],
            "answerable": True,
        }
        case.update(overrides)
        return case

    def test_scores_page_and_region_grounded_citation(self) -> None:
        prediction = self.prediction_with_citation(
            {
                "doc_id": "visual-doc",
                "chunk_id": "visual-doc::chunk-001",
                "page_span": [2, 2],
                "regions": [{"page_number": 2, "bbox": [10, 20, 120, 160]}],
            }
        )

        result = score_case(self.visual_case(), prediction)

        self.assertEqual(1.0, result["citation_page_precision"])
        self.assertEqual(1.0, result["citation_region_precision"])
        self.assertEqual(1.0, result["citation_grounding"])
        self.assertEqual([], result["citation_grounding_errors"])

    def test_scores_page_drift(self) -> None:
        prediction = self.prediction_with_citation(
            {
                "doc_id": "visual-doc",
                "chunk_id": "visual-doc::chunk-001",
                "page_span": [3, 3],
                "regions": [{"page_number": 3, "bbox": [10, 20, 120, 160]}],
            }
        )

        result = score_case(self.visual_case(expected_citation_regions=[]), prediction)

        self.assertEqual(0.0, result["citation_page_precision"])
        self.assertEqual(0.0, result["citation_grounding"])
        self.assertEqual("page_mismatch", result["citation_grounding_errors"][0]["code"])

    def test_scores_bbox_drift(self) -> None:
        prediction = self.prediction_with_citation(
            {
                "doc_id": "visual-doc",
                "chunk_id": "visual-doc::chunk-001",
                "page_span": [2, 2],
                "regions": [{"page_number": 2, "bbox": [200, 200, 260, 260]}],
            }
        )

        result = score_case(self.visual_case(expected_citation_pages=[]), prediction)

        self.assertEqual(0.0, result["citation_region_precision"])
        self.assertEqual(0.0, result["citation_grounding"])
        self.assertEqual("region_misaligned", result["citation_grounding_errors"][0]["code"])

    def test_scores_unavailable_region_metadata(self) -> None:
        prediction = self.prediction_with_citation(
            {
                "doc_id": "visual-doc",
                "chunk_id": "visual-doc::chunk-001",
                "page_span": [2, 2],
            }
        )

        result = score_case(self.visual_case(expected_citation_pages=[]), prediction)

        self.assertEqual(0.0, result["citation_region_precision"])
        self.assertEqual("region_unavailable", result["citation_grounding_errors"][0]["code"])

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
