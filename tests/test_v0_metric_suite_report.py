from __future__ import annotations

from scripts.render_v0_metric_suite_report import (
    STATUS_PARTIAL,
    STATUS_PRESENT,
    build_metric_suite,
    render_markdown,
)


def _aggregate() -> dict:
    return {
        "num_predictions": 3,
        "metrics": {
            "recall_at_5": 0.7,
            "recall_at_10": 0.8,
            "mrr_at_5": 0.6,
            "ndcg_at_5": 0.65,
        },
        "groundedness": 0.9,
        "citation_precision": 0.85,
        "claim_citation_alignment": 0.8,
        "comparison_target_recall": 1.0,
        "comparison_pool_recall": 0.5,
        "abstention": 0.75,
        "abstention_outcomes": {
            "correct_refusal": 3,
            "incorrect_answer": 1,
            "boundary_partial": 0,
        },
        "numeric_date_condition_accuracy": 0.66,
        "numeric_date_condition_slot_count": 9,
        "numeric_date_condition_type_counts": {"amount": 4, "date": 3, "numeric_or_score": 2},
        "ci": {
            "comparison_target_recall": {
                "mean": 1.0,
                "ci_lo": 1.0,
                "ci_hi": 1.0,
                "n": 2,
            }
        },
    }


def test_build_metric_suite_marks_implemented_families_present() -> None:
    report = build_metric_suite(
        _aggregate(),
        question_distribution={
            "question_type_distribution": {
                "amount_extraction": 5,
                "date_extraction": 2,
                "rfp_requirement": 8,
            }
        },
        judge_agreement={
            "n": 4,
            "cohens_kappa": 1.0,
            "spearman_rho": 1.0,
            "threshold": 0.6,
            "passes": True,
            "confusion": {},
        },
    )

    families = report["families"]
    assert families["retrieval_recall"]["status"] == STATUS_PRESENT
    assert families["comparison_coverage"]["status"] == STATUS_PRESENT
    assert families["numeric_date_condition_accuracy"]["status"] == STATUS_PRESENT
    assert families["human_judge_agreement"]["status"] == STATUS_PRESENT
    assert report["readiness"]["missing"] == 0


def test_build_metric_suite_keeps_human_agreement_partial_without_private_labels() -> None:
    report = build_metric_suite(_aggregate())

    family = report["families"]["human_judge_agreement"]
    assert family["status"] == STATUS_PARTIAL
    assert "requires_private_label_csv_or_approved_judge_aggregate" in family["notes"]


def test_markdown_report_is_aggregate_only() -> None:
    report = build_metric_suite(_aggregate())
    text = render_markdown(report)

    assert "metric-suite coverage report" in text
    assert "raw questions" in text.lower()
    assert "doc-1" not in text
    assert "chunk-1" not in text
