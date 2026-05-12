import tempfile
import unittest
from pathlib import Path

from eval.run_eval import (
    compute_run_manifest,
    cross_ablation_retry_precision,
    evaluate_run,
    load_config,
    retry_effectiveness_block,
    summarize_run,
)
from eval.scorers import score_case
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


class RetryEffectivenessTest(unittest.TestCase):
    """Regression tests for retry effectiveness block (issue #120).

    Cover the three pillars:
    - single-run metrics on case_results with mixed retry status
    - graceful empty-set fallback (no retries triggered)
    - cross-ablation precision joining agentic_full vs no_verifier_retry
    """

    def _case(
        self,
        *,
        cid: str,
        accuracy: float | None,
        retry_count: int,
        last_verified: bool | None,
    ) -> dict:
        return {
            "id": cid,
            "query_type": "single_doc",
            "accuracy": accuracy,
            "groundedness": accuracy,
            "citation_precision": accuracy,
            "claim_citation_alignment": accuracy,
            "answer_format_compliance": accuracy,
            "abstention": None,
            "latency_ms": 10.0,
            "retry_count": retry_count,
            "retry_trigger_reasons": ["topic_not_grounded"] if retry_count > 0 else [],
            "last_attempt_verified": last_verified,
        }

    def test_empty_case_set(self) -> None:
        block = retry_effectiveness_block([])
        self.assertEqual(0, block["cases_with_retry"])
        self.assertIsNone(block["recovery_rate"])
        self.assertIsNone(block["residual_failure_rate"])
        self.assertIsNone(block["retry_lift_vs_no_retry"])

    def test_no_retries_triggered(self) -> None:
        cases = [
            self._case(cid="a", accuracy=1.0, retry_count=0, last_verified=True),
            self._case(cid="b", accuracy=1.0, retry_count=0, last_verified=True),
        ]
        block = retry_effectiveness_block(cases)
        self.assertEqual(0, block["cases_with_retry"])
        self.assertEqual(2, block["cases_without_retry"])
        self.assertIsNone(block["recovery_rate"])

    def test_recovery_and_residual_complementary(self) -> None:
        # 4 retried cases: 3 correct, 1 wrong → recovery=0.75, residual=0.25
        cases = [
            self._case(cid="r1", accuracy=1.0, retry_count=1, last_verified=True),
            self._case(cid="r2", accuracy=1.0, retry_count=1, last_verified=True),
            self._case(cid="r3", accuracy=1.0, retry_count=1, last_verified=True),
            self._case(cid="r4", accuracy=0.0, retry_count=1, last_verified=False),
            self._case(cid="n1", accuracy=1.0, retry_count=0, last_verified=True),
        ]
        block = retry_effectiveness_block(cases)
        self.assertEqual(4, block["cases_with_retry"])
        self.assertEqual(1, block["cases_without_retry"])
        self.assertAlmostEqual(0.75, block["recovery_rate"])
        self.assertAlmostEqual(0.25, block["residual_failure_rate"])
        # 3 of 4 last attempts verified
        self.assertAlmostEqual(0.75, block["retry_resolution_rate"])
        # lift: 0.75 - 1.0 = -0.25 (retried cases worse than non-retried, expected)
        self.assertAlmostEqual(-0.25, block["retry_lift_vs_no_retry"])

    def test_resolution_rate_gracefully_skips_missing(self) -> None:
        # last_attempt_verified=None — should be excluded from resolution rate
        cases = [
            self._case(cid="r1", accuracy=1.0, retry_count=1, last_verified=None),
            self._case(cid="r2", accuracy=1.0, retry_count=1, last_verified=True),
        ]
        block = retry_effectiveness_block(cases)
        # Only 1 valid resolution flag → 1.0
        self.assertAlmostEqual(1.0, block["retry_resolution_rate"])

    def test_cross_ablation_precision(self) -> None:
        full = [
            # case 1: retried, baseline would fail → true positive
            self._case(cid="c1", accuracy=1.0, retry_count=1, last_verified=True),
            # case 2: retried, baseline would succeed → false positive
            self._case(cid="c2", accuracy=1.0, retry_count=1, last_verified=True),
            # case 3: retried, baseline also failed → true positive
            self._case(cid="c3", accuracy=0.0, retry_count=1, last_verified=False),
            # case 4: not retried → excluded
            self._case(cid="c4", accuracy=1.0, retry_count=0, last_verified=True),
        ]
        baseline = [
            self._case(cid="c1", accuracy=0.0, retry_count=0, last_verified=False),
            self._case(cid="c2", accuracy=1.0, retry_count=0, last_verified=True),
            self._case(cid="c3", accuracy=0.0, retry_count=0, last_verified=False),
            self._case(cid="c4", accuracy=1.0, retry_count=0, last_verified=True),
        ]
        result = cross_ablation_retry_precision(full, baseline)
        self.assertIsNotNone(result)
        self.assertEqual(3, result["n_retry_triggered"])
        self.assertEqual(2, result["true_positive_triggers"])
        self.assertEqual(1, result["false_positive_triggers"])
        # 2 / (2 + 1) ≈ 0.6667
        self.assertAlmostEqual(2 / 3, result["retry_precision"], places=4)
        self.assertEqual(
            "cross_ablation(agentic_full,no_verifier_retry)", result["method"]
        )

    def test_cross_ablation_returns_none_without_baseline(self) -> None:
        full = [
            self._case(cid="c1", accuracy=1.0, retry_count=1, last_verified=True),
        ]
        self.assertIsNone(cross_ablation_retry_precision(full, []))
        self.assertIsNone(cross_ablation_retry_precision([], full))

    def test_summary_exposes_retry_effectiveness(self) -> None:
        cases = [
            self._case(cid="a", accuracy=1.0, retry_count=1, last_verified=True),
            self._case(cid="b", accuracy=0.0, retry_count=1, last_verified=False),
        ]
        summary = summarize_run("unit", {"pipeline": "agentic_full"}, cases)
        self.assertIn("retry_effectiveness", summary)
        self.assertEqual(2, summary["retry_effectiveness"]["cases_with_retry"])
        self.assertAlmostEqual(
            0.5, summary["retry_effectiveness"]["recovery_rate"]
        )


class RunManifestTest(unittest.TestCase):
    """Regression test for run_manifest schema (issue #120 pre-stack)."""

    def test_manifest_has_expected_keys(self) -> None:
        manifest = compute_run_manifest(ROOT_DIR / "eval" / "config.yaml")
        self.assertIn("git_commit", manifest)
        self.assertIn("git_dirty", manifest)
        self.assertIn("config_path", manifest)
        self.assertIn("config_sha256", manifest)
        self.assertIn("generated_at", manifest)
        # Generated timestamp ends with Z (UTC) per spec.
        self.assertTrue(manifest["generated_at"].endswith("Z"))
        # SHA is truncated 16-char hex.
        self.assertEqual(16, len(manifest["config_sha256"]))
        # Stable: hashing the same file twice gives the same SHA.
        again = compute_run_manifest(ROOT_DIR / "eval" / "config.yaml")
        self.assertEqual(manifest["config_sha256"], again["config_sha256"])

    def test_manifest_handles_missing_config_gracefully(self) -> None:
        manifest = compute_run_manifest(Path("/nonexistent/eval.yaml"))
        self.assertEqual("unknown", manifest["config_sha256"])


if __name__ == "__main__":
    unittest.main()
