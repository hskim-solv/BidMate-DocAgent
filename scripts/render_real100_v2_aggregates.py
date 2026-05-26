#!/usr/bin/env python3
"""Render aggregate-only real100_v2 baseline and tier reports.

Inputs may be private local files. Outputs are aggregate-only and must not
include raw questions, answers, evidence, document IDs, chunk IDs, filenames,
paths, or per-case rows.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.private_data_quality_audit_utils import assert_public_safe  # noqa: E402
from scripts.run_real_eval_delta import extract_aggregate  # noqa: E402

TIERS = ("easy_sanity", "standard_real", "hard_stress")
METRIC_FIELDS = {
    "recall_at_5": "chunk_recall_at_5",
    "recall_at_10": "chunk_recall_at_10",
    "mrr_at_5": "chunk_mrr_at_5",
    "ndcg_at_5": "chunk_ndcg_at_5",
    "citation_precision": "citation_precision",
    "citation_accuracy": "citation_grounding",
    "abstention": "abstention",
}
BASELINE_METRIC_FIELDS = {
    "recall_at_5": "chunk_recall_at_5",
    "recall_at_10": "chunk_recall_at_10",
    "mrr_at_5": "chunk_mrr_at_5",
    "ndcg_at_5": "chunk_ndcg_at_5",
    "citation_precision": "citation_precision",
    "citation_accuracy": "citation_grounding",
    "abstention": "abstention",
}
SAFE_FAILURE_LABELS = {
    "retrieval_miss",
    "wrong_doc",
    "wrong_chunk",
    "citation_miss",
    "unsupported",
    "abstention_miss",
    "false_abstention",
    "none",
    "unknown",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _load_question_tiers(path: Path) -> dict[str, str]:
    tiers: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("question_id") or "")
            tier = str(row.get("difficulty_tier") or "")
            if qid and tier in TIERS:
                tiers[qid] = tier
    return tiers


def _mean_block(cases: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values: list[float] = []
    missing = 0
    for case in cases:
        value = case.get(field)
        if isinstance(value, bool):
            values.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            values.append(float(value))
        else:
            missing += 1
    return {
        "mean": (sum(values) / len(values)) if values else None,
        "n": len(values),
        "missing": missing,
    }


def _safe_failure(value: Any) -> str:
    label = str(value or "none")
    return label if label in SAFE_FAILURE_LABELS else "unknown"


def render_tiers(summary: dict[str, Any], question_tiers: dict[str, str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {tier: [] for tier in TIERS}
    unknown_tier = 0
    for case in summary.get("case_results") or []:
        if not isinstance(case, dict):
            continue
        tier = question_tiers.get(str(case.get("id") or ""))
        if tier in grouped:
            grouped[tier].append(case)
        else:
            unknown_tier += 1

    tiers: dict[str, Any] = {}
    for tier in TIERS:
        cases = grouped[tier]
        failure_counts = Counter(_safe_failure(case.get("failure_category")) for case in cases)
        abstention_outcomes: Counter[str] = Counter()
        for case in cases:
            answerable = bool(case.get("answerable"))
            abstained = bool(case.get("abstained"))
            if answerable and abstained:
                abstention_outcomes["false_abstention"] += 1
            elif not answerable and abstained:
                abstention_outcomes["correct_abstention"] += 1
            elif not answerable and not abstained:
                abstention_outcomes["missed_abstention"] += 1
            else:
                abstention_outcomes["not_applicable"] += 1
        metrics = {
            public_name: _mean_block(cases, field)
            for public_name, field in METRIC_FIELDS.items()
        }
        tiers[tier] = {
            "n": len(cases),
            "metrics": metrics,
            "abstention_outcomes": dict(sorted(abstention_outcomes.items())),
            "failure_distribution": dict(sorted(failure_counts.items())),
            "dominant_failure_category": (
                failure_counts.most_common(1)[0][0] if failure_counts else None
            ),
        }

    aggregate = {
        "schema_version": 1,
        "profile_type": "private_real100_v2_benchmark_tiers",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "eval_summary": {"artifact": "private_local_eval_summary"},
            "question_tiers": {"artifact": "private_local_question_set"},
        },
        "tier_criteria": {
            "easy_sanity": [
                "answerable",
                "single-doc",
                "single-chunk",
                "clear expected terms",
                "not table-heavy",
                "not multi-hop",
                "no similar-clause distractor proxy",
            ],
            "standard_real": [
                "normal RFP QA",
                "date amount score schedule requirement extraction allowed",
                "moderate distractors allowed",
            ],
            "hard_stress": [
                "multi-chunk",
                "multi-doc",
                "table-heavy",
                "similar-clause distractors",
                "unanswerable",
                "citation/page dependent",
                "parser-stress",
            ],
        },
        "tiers": tiers,
        "unknown_tier_case_count": unknown_tier,
        "interpretation_policy": (
            "Tiering is for interpretation and comparison, not cherry-picking "
            "headline claims. Future PRs should compare overall plus every tier."
        ),
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
    assert_public_safe(aggregate)
    return aggregate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-summary", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--baseline-out", type=Path, required=True)
    parser.add_argument("--tiers-out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = _load_json(args.eval_summary)
    baseline = extract_aggregate(summary)
    baseline["metrics"] = {
        public_name: summary.get(source_name)
        for public_name, source_name in BASELINE_METRIC_FIELDS.items()
    }
    baseline["profile_type"] = "private_real100_v2_baseline"
    baseline["privacy"] = {
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
    }
    assert_public_safe(baseline)
    tiers = render_tiers(summary, _load_question_tiers(args.questions))

    args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
    args.baseline_out.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.tiers_out.parent.mkdir(parents=True, exist_ok=True)
    args.tiers_out.write_text(
        json.dumps(tiers, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] wrote aggregate real100_v2 baseline: {args.baseline_out}")
    print(f"[OK] wrote aggregate real100_v2 tiers: {args.tiers_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
