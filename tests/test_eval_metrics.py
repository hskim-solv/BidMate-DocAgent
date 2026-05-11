import tempfile
import unittest
from pathlib import Path

from eval.run_eval import evaluate_run, load_config, score_case, summarize_run
from rag_core import build_index_payload


ROOT_DIR = Path(__file__).resolve().parents[1]


class EvalMetricsTest(unittest.TestCase):
    def prediction_with_citation(self, citation: dict) -> dict:
        return {
            "answer": {
                "schema_version": 2,
                "status": "supported",
                "status_reason": {
                    "code": "verified",
                    "verified": True,
                    "verification_reasons": [],
                },
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

    def test_score_case_emits_evidence_for_judge_consumers(self) -> None:
        """score_case must expose top-3 evidence with {text, doc_id,
        chunk_id, page} for scripts/llm_judge.py + eval/synthetic_judge.py
        (ADR 0006 + ADR 0012). Text is truncated to 600 chars."""
        long_text = "가" * 1000
        prediction = {
            "answer": {
                "schema_version": 2,
                "status": "supported",
                "claims": [],
            },
            "answer_text": "answer",
            "evidence": [
                {"doc_id": "d1", "chunk_id": "d1::c1", "text": long_text, "page": 1},
                {"doc_id": "d2", "chunk_id": "d2::c2", "text": "short", "page": 2},
                {"doc_id": "d3", "chunk_id": "d3::c3", "text": "third", "page": 3},
                {"doc_id": "d4", "chunk_id": "d4::c4", "text": "fourth", "page": 4},
            ],
            "diagnostics": {"latency_ms": 1.0, "retry_count": 0},
        }
        result = score_case(self.visual_case(), prediction)
        self.assertIn("evidence", result)
        evidence = result["evidence"]
        # Top 3 only.
        self.assertEqual(len(evidence), 3)
        # Text is truncated to 600 chars.
        self.assertEqual(len(evidence[0]["text"]), 600)
        # All four schema keys present.
        for item in evidence:
            self.assertEqual(set(item), {"text", "doc_id", "chunk_id", "page"})
        # Ordering preserved from prediction.evidence.
        self.assertEqual([e["doc_id"] for e in evidence], ["d1", "d2", "d3"])

    def test_score_case_evidence_handles_empty(self) -> None:
        prediction = {
            "answer": {"schema_version": 2, "status": "insufficient", "claims": []},
            "answer_text": "",
            "evidence": [],
            "diagnostics": {"latency_ms": 1.0, "retry_count": 0},
        }
        result = score_case(self.visual_case(), prediction)
        self.assertEqual(result["evidence"], [])

    def test_summarize_run_groups_metrics_by_hardcase_category(self) -> None:
        case_results = [
            {
                "query_type": "single_doc",
                "hardcase_categories": ["scanned_pdf", "noisy_ocr"],
                "accuracy": 1.0,
                "groundedness": 1.0,
                "citation_precision": 0.5,
                "claim_citation_alignment": 1.0,
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
                "claim_citation_alignment": 0.0,
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

    def test_scores_claim_citation_alignment_separately_from_whole_answer(self) -> None:
        prediction = {
            "answer": {
                "schema_version": 2,
                "status": "supported",
                "status_reason": {
                    "code": "verified",
                    "verified": True,
                    "verification_reasons": [],
                },
                "claims": [
                    {
                        "target": "기관 V",
                        "claim": "기관 V의 보안 요구사항은 접근 통제입니다.",
                        "support": "기관 V의 보안 요구사항은 접근 통제입니다.",
                        "citations": [
                            {
                                "doc_id": "visual-doc",
                                "chunk_id": "visual-doc::chunk-002",
                            }
                        ],
                    }
                ],
            },
            "answer_text": "기관 V의 보안 요구사항은 접근 통제입니다.",
            "evidence": [
                {
                    "doc_id": "visual-doc",
                    "chunk_id": "visual-doc::chunk-001",
                    "text": "기관 V의 보안 요구사항은 접근 통제입니다.",
                },
                {
                    "doc_id": "visual-doc",
                    "chunk_id": "visual-doc::chunk-002",
                    "text": "기관 V의 일정은 3개월입니다.",
                },
            ],
            "diagnostics": {"latency_ms": 1.0, "retry_count": 0},
        }

        result = score_case(
            self.visual_case(
                expected_citation_pages=[],
                expected_citation_regions=[],
                expected_claim_citations=[
                    {
                        "target": "기관 V",
                        "expected_doc_ids": ["visual-doc"],
                        "expected_terms": ["보안 요구사항", "접근 통제"],
                    }
                ],
            ),
            prediction,
        )

        self.assertEqual(1.0, result["citation_precision"])
        self.assertEqual(0.0, result["claim_citation_alignment"])
        self.assertEqual(
            "claim_text_not_supported_by_citation",
            result["claim_citation_errors"][0]["code"],
        )

    def test_evaluate_run_writes_readable_trace_files(self) -> None:
        index = build_index_payload(Path("data/raw"), embedding_backend="hashing")
        case = {
            "id": "trace-case",
            "query_type": "single_doc",
            "query": "기관 A의 보안 통제 요구사항은?",
            "expected_doc_ids": ["rfp-agency-a-ai-quality"],
            "expected_terms": ["보안 통제", "로그"],
            "expected_claim_targets": ["기관 A"],
            "answerable": True,
        }
        run_config = {
            "name": "unit",
            "pipeline": "agentic_full",
            "top_k": None,
            "metadata_first": True,
            "rerank": True,
            "verifier_retry": True,
            "retrieval_mode": "flat",
            "prompt_profile": "structured_grounded_claims",
        }
        with tempfile.TemporaryDirectory() as tmp:
            results = evaluate_run(index, [case], run_config, trace_dir=Path(tmp))
            trace_path = Path(results[0]["trace_path"])
            payload = trace_path.read_text(encoding="utf-8")

        self.assertIn("planner", payload)
        self.assertIn("query_rewrite", payload)
        self.assertIn("readable_summary", payload)

    def test_private_hardcase_example_config_loads(self) -> None:
        config = load_config(ROOT_DIR / "eval" / "private_hardcase.example.yaml")

        self.assertEqual("visual_v2_full", config["primary_run"])
        self.assertEqual(
            ["scanned_pdf", "noisy_ocr"],
            config["cases"][0]["hardcase_categories"],
        )


if __name__ == "__main__":
    unittest.main()
