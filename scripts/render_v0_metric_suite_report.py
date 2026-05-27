#!/usr/bin/env python3
"""Render a v0 metric-suite report from aggregate-only real-eval artifacts.

The input aggregate is already past the ADR 0005 commit boundary. Optional
judge/human labels are local-only CSV input; only agreement aggregates cross
into the output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judges.judge_agreement import compute_agreement, load_labels  # noqa: E402
from scripts.private_data_quality_audit_utils import assert_public_safe  # noqa: E402


STATUS_PRESENT = "present"
STATUS_PARTIAL = "partial"
STATUS_MISSING = "missing"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _first_metric(aggregate: dict[str, Any], *keys: str) -> Any:
    metrics = aggregate.get("metrics") if isinstance(aggregate.get("metrics"), dict) else {}
    ci = aggregate.get("ci") if isinstance(aggregate.get("ci"), dict) else {}
    for key in keys:
        value = aggregate.get(key)
        if value is not None:
            return value
        value = metrics.get(key)
        if value is not None:
            return value
        ci_block = ci.get(key)
        if isinstance(ci_block, dict) and ci_block.get("mean") is not None:
            return ci_block.get("mean")
    return None


def _ci(aggregate: dict[str, Any], key: str) -> dict[str, Any] | None:
    ci = aggregate.get("ci")
    if not isinstance(ci, dict):
        return None
    block = ci.get(key)
    return block if isinstance(block, dict) else None


def _status(*values: Any) -> str:
    present = [value is not None for value in values]
    if all(present):
        return STATUS_PRESENT
    if any(present):
        return STATUS_PARTIAL
    return STATUS_MISSING


def _family(status: str, metrics: dict[str, Any], *, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "metrics": metrics,
        "notes": notes or [],
    }


def _question_type_counts(question_distribution: dict[str, Any] | None) -> dict[str, int]:
    if not question_distribution:
        return {}
    raw = question_distribution.get("question_type_distribution")
    if not isinstance(raw, dict):
        return {}
    safe_prefixes = (
        "amount",
        "date",
        "score",
        "table_heavy_score_or_amount",
        "multi_doc_amount",
    )
    out: dict[str, int] = {}
    for key, value in raw.items():
        if not str(key).startswith(safe_prefixes):
            continue
        if isinstance(value, (int, float)):
            out[str(key)] = int(value)
    return out


def build_metric_suite(
    aggregate: dict[str, Any],
    *,
    question_distribution: dict[str, Any] | None = None,
    judge_agreement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retrieval = {
        "chunk_recall_at_5": _first_metric(aggregate, "chunk_recall_at_5", "recall_at_5"),
        "chunk_recall_at_10": _first_metric(aggregate, "chunk_recall_at_10", "recall_at_10"),
        "chunk_mrr": _first_metric(aggregate, "chunk_mrr", "mrr_at_5"),
        "chunk_ndcg": _first_metric(aggregate, "chunk_ndcg_at_10", "ndcg_at_5"),
    }
    grounding = {
        "groundedness": _first_metric(aggregate, "groundedness"),
        "citation_grounding": _first_metric(aggregate, "citation_grounding"),
        "citation_page_precision": _first_metric(aggregate, "citation_page_precision"),
        "citation_region_precision": _first_metric(aggregate, "citation_region_precision"),
    }
    comparison = {
        "comparison_target_recall": _first_metric(aggregate, "comparison_target_recall"),
        "comparison_pool_recall": _first_metric(aggregate, "comparison_pool_recall"),
        "comparison_target_full_coverage_rate": _first_metric(
            aggregate,
            "comparison_target_full_coverage_rate",
        ),
        "comparison_pool_full_coverage_rate": _first_metric(
            aggregate,
            "comparison_pool_full_coverage_rate",
        ),
    }
    abstention_calibration = aggregate.get("abstention_calibration")
    abstention = {
        "abstention": _first_metric(aggregate, "abstention"),
        "abstention_outcomes": aggregate.get("abstention_outcomes"),
        "abstention_calibration": abstention_calibration,
    }
    slot_metrics = {
        "numeric_date_condition_accuracy": _first_metric(
            aggregate,
            "numeric_date_condition_accuracy",
        ),
        "numeric_date_condition_slot_count": _first_metric(
            aggregate,
            "numeric_date_condition_slot_count",
        ),
        "numeric_date_condition_type_counts": aggregate.get(
            "numeric_date_condition_type_counts"
        ),
        "question_type_counts": _question_type_counts(question_distribution),
    }
    human_judge = judge_agreement or aggregate.get("human_judge_agreement")

    families = {
        "retrieval_recall": _family(
            _status(retrieval["chunk_recall_at_10"], retrieval["chunk_mrr"]),
            retrieval,
        ),
        "grounding": _family(
            STATUS_PRESENT if grounding["groundedness"] is not None else STATUS_MISSING,
            grounding,
            notes=(
                []
                if grounding["citation_grounding"] is not None
                else ["page_region_grounding_not_populated"]
            ),
        ),
        "citation_precision": _family(
            _status(_first_metric(aggregate, "citation_precision")),
            {"citation_precision": _first_metric(aggregate, "citation_precision")},
        ),
        "claim_citation_alignment": _family(
            _status(_first_metric(aggregate, "claim_citation_alignment")),
            {"claim_citation_alignment": _first_metric(aggregate, "claim_citation_alignment")},
        ),
        "comparison_coverage": _family(
            _status(comparison["comparison_target_recall"], comparison["comparison_pool_recall"]),
            comparison,
        ),
        "abstention_calibration": _family(
            _status(abstention["abstention"], abstention["abstention_outcomes"]),
            abstention,
            notes=(
                []
                if isinstance(abstention_calibration, dict)
                else ["confidence_calibration_not_populated"]
            ),
        ),
        "numeric_date_condition_accuracy": _family(
            _status(
                slot_metrics["numeric_date_condition_accuracy"],
                slot_metrics["numeric_date_condition_slot_count"],
            ),
            slot_metrics,
            notes=(
                []
                if slot_metrics["numeric_date_condition_accuracy"] is not None
                else ["requires_eval_regeneration_with_issue_1544_scorer"]
            ),
        ),
        "human_judge_agreement": _family(
            STATUS_PRESENT if isinstance(human_judge, dict) else STATUS_PARTIAL,
            human_judge or {},
            notes=(
                []
                if isinstance(human_judge, dict)
                else ["requires_private_label_csv_or_approved_judge_aggregate"]
            ),
        ),
    }
    status_counts = {
        status: sum(1 for family in families.values() if family["status"] == status)
        for status in (STATUS_PRESENT, STATUS_PARTIAL, STATUS_MISSING)
    }
    report = {
        "schema_version": 1,
        "profile_type": "v0_metric_suite_report",
        "source": {
            "primary_aggregate": "private_real_eval_aggregate",
            "question_distribution": (
                "private_real_eval_question_distribution"
                if question_distribution is not None
                else None
            ),
            "judge_agreement": "local_private_csv_aggregate" if judge_agreement else None,
        },
        "claim_boundary": {
            "performance_claim": False,
            "purpose": "metric_suite_adoption_and_gap_tracking",
            "requires_private_real_eval_delta_for_performance_claim": True,
        },
        "families": families,
        "readiness": {
            **status_counts,
            "all_present": status_counts[STATUS_PRESENT] == len(families),
        },
        "ci": {
            key: block
            for key in (
                "chunk_recall_at_10",
                "groundedness",
                "citation_precision",
                "claim_citation_alignment",
                "comparison_target_recall",
                "comparison_pool_recall",
                "numeric_date_condition_accuracy",
                "abstention",
            )
            if (block := _ci(aggregate, key)) is not None
        },
        "privacy": {
            "aggregate_only": True,
            "raw_questions_omitted": True,
            "raw_answers_omitted": True,
            "raw_evidence_omitted": True,
            "raw_text_omitted": True,
            "doc_ids_omitted": True,
            "chunk_ids_omitted": True,
            "filenames_omitted": True,
            "paths_omitted": True,
            "per_case_rows_omitted": True,
        },
    }
    assert_public_safe(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    families = report["families"]
    lines = [
        "# v0 Metric Suite Report",
        "",
        "This is an aggregate-only metric-suite coverage report, not a performance claim.",
        "",
        "| Family | Status | Metrics | Notes |",
        "|---|---|---|---|",
    ]
    for name, family in families.items():
        metrics = family.get("metrics") or {}
        metric_names = ", ".join(f"`{key}`" for key, value in metrics.items() if value is not None)
        if not metric_names:
            metric_names = "N/A"
        notes = "; ".join(str(note) for note in family.get("notes") or []) or "N/A"
        lines.append(f"| `{name}` | `{family['status']}` | {metric_names} | {notes} |")
    readiness = report["readiness"]
    lines.extend(
        [
            "",
            "## Readiness",
            "",
            f"- present: {readiness['present']}",
            f"- partial: {readiness['partial']}",
            f"- missing: {readiness['missing']}",
            f"- all_present: `{str(readiness['all_present']).lower()}`",
            "",
            "Private raw questions, answers, evidence, document IDs, chunk IDs, filenames, paths, and per-case rows are omitted.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--question-distribution", type=Path)
    parser.add_argument("--judge-agreement-csv", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    aggregate = _load_json(args.aggregate)
    question_distribution = (
        _load_json(args.question_distribution) if args.question_distribution else None
    )
    judge_agreement = None
    if args.judge_agreement_csv:
        judge_agreement = compute_agreement(load_labels(args.judge_agreement_csv))
    report = build_metric_suite(
        aggregate,
        question_distribution=question_distribution,
        judge_agreement=judge_agreement,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"[OK] wrote v0 metric suite aggregate: {args.out_json}")
    print(f"[OK] wrote v0 metric suite report: {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
