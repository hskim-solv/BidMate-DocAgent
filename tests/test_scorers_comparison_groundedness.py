"""Target-aware comparison groundedness scorer (issue #1399, ADR 0073).

The pooled ``groundedness`` (``eval/scorers/case.py``) merges the answer + *all*
evidence into one blob and checks ``contains_all_terms`` globally. For a 2-target
comparison it cannot tell "both sides independently grounded" from "one side
grounded, the other side's expected terms merely leaking into the shared pool".

The headline test below (`TestOneSidedLeakage`) pins the exact failure class: a
one-sided answer where target B's terms leak into target A's evidence chunk scores
**pooled groundedness = 1.0 but comparison_groundedness = 0.5** — proving the new
metric catches what the old one misses. The remaining cases lock the boundary
semantics (both-grounded, missing gold, non-comparison, abstention, unanswerable)
and the ``metric_block`` aggregation.
"""
from __future__ import annotations

import unittest

from eval.run_eval import metric_block
from eval.scorers.case import score_case


def _prediction(
    *,
    answer_status: str = "supported",
    summary: str = "",
    claims: list[dict[str, object]] | None = None,
    evidence: list[dict[str, object]] | None = None,
    abstained: bool = False,
) -> dict[str, object]:
    return {
        "answer": {
            "schema_version": 2,
            "status": answer_status,
            "summary": summary,
            "claims": claims or [],
            "insufficiency": {"missing_targets": []},
            "confidence": None,
        },
        "evidence": evidence or [],
        "diagnostics": {
            "abstained": abstained,
            "latency_ms": 100.0,
            "retry_count": 0,
            "filter_stage_attempts": [],
            "stage_latency": {},
            "retrieved_chunk_ids": [],
        },
        "plan": {},
        "analysis": {},
    }


def _comparison_case() -> dict[str, object]:
    """2-target comparison case mirroring eval/config.yaml comparison gold."""
    return {
        "id": "cmp_ai_requirements",
        "query_type": "comparison",
        "answerable": True,
        "expected_doc_ids": ["doc_a", "doc_b"],
        "expected_terms": ["품질관리", "MLOps"],
        "expected_citation_terms": ["품질관리", "MLOps"],
        "expected_claim_citations": [
            {"target": "기관 A", "expected_doc_ids": ["doc_a"], "expected_terms": ["품질관리"]},
            {"target": "기관 B", "expected_doc_ids": ["doc_b"], "expected_terms": ["MLOps"]},
        ],
    }


class TestOneSidedLeakage(unittest.TestCase):
    """THE failure class: B's term leaks into A's evidence; B has no own evidence.

    Pooled groundedness sees both expected_terms in the combined blob → 1.0
    (false positive). Per-target grounding sees doc_b unground → 0.5.
    """

    def test_pooled_one_per_target_half(self) -> None:
        case = _comparison_case()
        # Only doc_a evidence — and it happens to mention BOTH terms. doc_b
        # (target 기관 B) has no evidence of its own.
        prediction = _prediction(
            summary="기관 A는 품질관리를 요구하고 MLOps도 언급한다.",
            evidence=[
                {"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "품질관리 요구사항. MLOps 언급."},
            ],
        )
        result = score_case(case, prediction)
        # Old pooled metric: term_match over answer+all-evidence → both terms present.
        self.assertEqual(result["groundedness"], 1.0)
        # New target-aware metric: only 기관 A grounded by its own doc → 1/2.
        self.assertEqual(result["comparison_groundedness"], 0.5)


class TestBothGrounded(unittest.TestCase):
    def test_both_targets_full(self) -> None:
        case = _comparison_case()
        prediction = _prediction(
            summary="기관 A 품질관리 / 기관 B MLOps",
            evidence=[
                {"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "품질관리 통제 요구."},
                {"doc_id": "doc_b", "chunk_id": "doc_b:0", "text": "MLOps 거버넌스 요구."},
            ],
        )
        result = score_case(case, prediction)
        self.assertEqual(result["groundedness"], 1.0)
        self.assertEqual(result["comparison_groundedness"], 1.0)


class TestNeitherGrounded(unittest.TestCase):
    def test_wrong_docs_zero(self) -> None:
        case = _comparison_case()
        # Evidence from unrelated docs — neither target's own doc present.
        prediction = _prediction(
            summary="품질관리 MLOps",
            evidence=[
                {"doc_id": "doc_x", "chunk_id": "doc_x:0", "text": "품질관리 MLOps 둘 다 언급."},
            ],
        )
        result = score_case(case, prediction)
        # Pooled: both terms in combined blob → 1.0 (false positive again).
        self.assertEqual(result["groundedness"], 1.0)
        # Per-target: neither doc_a nor doc_b in evidence → 0/2.
        self.assertEqual(result["comparison_groundedness"], 0.0)


class TestExcludedCases(unittest.TestCase):
    def test_non_comparison_is_none(self) -> None:
        case = {
            "id": "single",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["품질관리"],
            "expected_claim_citations": [
                {"target": "기관 A", "expected_doc_ids": ["doc_a"], "expected_terms": ["품질관리"]},
            ],
        }
        prediction = _prediction(
            evidence=[{"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "품질관리"}],
        )
        self.assertIsNone(score_case(case, prediction)["comparison_groundedness"])

    def test_comparison_without_per_target_gold_is_none(self) -> None:
        case = {
            "id": "cmp_single_target",
            "query_type": "comparison",
            "answerable": True,
            "expected_doc_ids": ["doc_a", "doc_b"],
            "expected_terms": ["품질관리"],
            "expected_claim_citations": [
                {"target": "기관 A", "expected_doc_ids": ["doc_a"], "expected_terms": ["품질관리"]},
            ],
        }
        prediction = _prediction(
            evidence=[{"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "품질관리"}],
        )
        # Only 1 target spec → not a multi-target comparison → excluded (None).
        self.assertIsNone(score_case(case, prediction)["comparison_groundedness"])

    def test_unanswerable_is_none(self) -> None:
        case = dict(_comparison_case(), answerable=False)
        prediction = _prediction(answer_status="insufficient", abstained=True)
        self.assertIsNone(score_case(case, prediction)["comparison_groundedness"])

    def test_answerable_abstention_is_zero(self) -> None:
        case = _comparison_case()
        prediction = _prediction(answer_status="insufficient", abstained=True)
        # Answerable comparison the model refused → 0.0 (penalized, not None),
        # mirroring pooled groundedness on the answerable-but-refused path.
        self.assertEqual(score_case(case, prediction)["comparison_groundedness"], 0.0)


class TestMetricBlockAggregation(unittest.TestCase):
    """metric_block averages only the non-None comparison scores and adds CI."""

    def test_block_mean_and_ci(self) -> None:
        case = _comparison_case()
        results = [
            score_case(
                case,
                _prediction(
                    evidence=[
                        {"doc_id": "doc_a", "chunk_id": "a", "text": "품질관리"},
                        {"doc_id": "doc_b", "chunk_id": "b", "text": "MLOps"},
                    ]
                ),
            ),  # 1.0
            score_case(
                case,
                _prediction(evidence=[{"doc_id": "doc_a", "chunk_id": "a", "text": "품질관리"}]),
            ),  # 0.5
            # Non-comparison case contributes None → excluded from denominator.
            score_case(
                {
                    "id": "s",
                    "query_type": "single_doc",
                    "answerable": True,
                    "expected_doc_ids": ["doc_a"],
                    "expected_terms": ["품질관리"],
                },
                _prediction(evidence=[{"doc_id": "doc_a", "chunk_id": "a", "text": "품질관리"}]),
            ),
        ]
        block = metric_block(results)
        self.assertAlmostEqual(block["comparison_groundedness"], 0.75, places=6)
        self.assertIn("comparison_groundedness", block["ci"])
        self.assertEqual(block["num_predictions"], 3)


if __name__ == "__main__":
    unittest.main()
