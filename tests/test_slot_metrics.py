from __future__ import annotations

from eval.run_eval import metric_block, numeric_date_condition_summary_fields
from eval.scorers import score_case, score_numeric_date_condition_slots


def test_slot_exactness_normalizes_amount_and_date_forms() -> None:
    result = score_numeric_date_condition_slots(
        ["5천만원", "2026년 3월 15일"],
        "예산은 50,000,000원이고 마감일은 2026-03-15입니다.",
    )

    assert result["numeric_date_condition_accuracy"] == 1.0
    assert result["numeric_date_condition_slot_count"] == 2
    assert result["numeric_date_condition_type_counts"] == {"amount": 1, "date": 1}


def test_slot_exactness_returns_none_when_not_applicable() -> None:
    result = score_numeric_date_condition_slots(["보안 요구사항"], "보안 요구사항")

    assert result["numeric_date_condition_accuracy"] is None
    assert result["numeric_date_condition_slot_count"] == 0


def test_score_case_emits_numeric_date_condition_accuracy() -> None:
    case = {
        "id": "c1",
        "query_type": "single_doc",
        "answerable": True,
        "expected_doc_ids": ["doc-1"],
        "expected_terms": ["5천만원"],
    }
    prediction = {
        "answer": {"summary": "예산은 50,000,000원입니다.", "claims": []},
        "evidence": [{"doc_id": "doc-1", "text": "총 예산 50,000,000원"}],
        "diagnostics": {},
        "plan": {},
        "analysis": {},
    }

    result = score_case(case, prediction)

    assert result["numeric_date_condition_accuracy"] == 1.0
    assert result["numeric_date_condition_slot_count"] == 1
    assert result["numeric_date_condition_type_counts"] == {"amount": 1}


def test_metric_block_aggregates_slot_exactness() -> None:
    block = metric_block(
        [
            {
                "accuracy": 1.0,
                "groundedness": 1.0,
                "citation_precision": 1.0,
                "claim_citation_alignment": 1.0,
                "abstention": None,
                "answer_format_compliance": 1.0,
                "numeric_date_condition_accuracy": 1.0,
                "numeric_date_condition_slot_count": 2,
                "numeric_date_condition_type_counts": {"amount": 1, "date": 1},
                "numeric_date_condition_type_correct_counts": {"amount": 1, "date": 1},
                "latency_ms": 10.0,
                "retry_count": 0,
                "retry_trigger_reasons": [],
                "cold_start": False,
                "stage_latency": {},
                "attempt_latency": [],
            },
            {
                "accuracy": 0.0,
                "groundedness": 0.0,
                "citation_precision": 0.0,
                "claim_citation_alignment": 0.0,
                "abstention": None,
                "answer_format_compliance": 1.0,
                "numeric_date_condition_accuracy": 0.0,
                "numeric_date_condition_slot_count": 1,
                "numeric_date_condition_type_counts": {"amount": 1},
                "numeric_date_condition_type_correct_counts": {},
                "latency_ms": 20.0,
                "retry_count": 0,
                "retry_trigger_reasons": [],
                "cold_start": False,
                "stage_latency": {},
                "attempt_latency": [],
            },
        ]
    )

    assert block["numeric_date_condition_accuracy"] == 0.5
    assert block["numeric_date_condition_slot_count"] == 3
    assert block["numeric_date_condition_type_counts"] == {"amount": 2, "date": 1}
    assert block["numeric_date_condition_type_correct_counts"] == {"amount": 1, "date": 1}
    assert "numeric_date_condition_accuracy" in block["ci"]


def test_summary_fields_pass_through_slot_exactness() -> None:
    fields = numeric_date_condition_summary_fields(
        {
            "numeric_date_condition_accuracy": 0.5,
            "numeric_date_condition_slot_count": 3,
            "numeric_date_condition_type_counts": {"amount": 2, "date": 1},
            "numeric_date_condition_type_correct_counts": {"amount": 1, "date": 1},
        }
    )

    assert fields == {
        "numeric_date_condition_accuracy": 0.5,
        "numeric_date_condition_slot_count": 3,
        "numeric_date_condition_type_counts": {"amount": 2, "date": 1},
        "numeric_date_condition_type_correct_counts": {"amount": 1, "date": 1},
    }
