#!/usr/bin/env python3
"""Render verifier_false_negative overlap slices as redacted aggregates.

Reads the local-only ``reports/real100/eval_summary.json`` case results and
writes aggregate-only JSON/Markdown. The renderer is a read-only measurement
surface: it does not import or change retrieval/verifier runtime behavior.

ADR 0005 boundary: raw query text, generated answers, evidence text, doc_id,
chunk_id, file/path values, and case ids are consumed only to derive counts or
closed enum buckets. They are never copied into the output payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.failure_classifier import (  # noqa: E402
    FAILURE_CATEGORIES,
    classify_failure,
)

DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_JSON = (
    ROOT / "reports" / "real100" / "verifier_false_negative_overlap.aggregate.json"
)
DEFAULT_OUT_MD = ROOT / "docs" / "audits" / "verifier-false-negative-overlap-analysis.md"
DEFAULT_SOURCE_PROVENANCE = {
    "location": "reports/real100/eval_summary.json",
    "location_redacted": False,
    "basename": "eval_summary.json",
    "sha256_12": None,
}

SAFE_CATEGORIES: tuple[str, ...] = FAILURE_CATEGORIES
SAFE_QUERY_TYPES: tuple[str, ...] = (
    "single_doc",
    "comparison",
    "follow_up",
    "abstention",
)
SAFE_HARDCASE: tuple[str, ...] = (
    "multi_hop",
    "distractor_heavy",
    "long_context",
    "no_answer",
    "ambiguous_query",
)
RETRY_BUCKETS: tuple[str, ...] = ("0", "1", "2", "3plus")
EXPECTED_CARDINALITY_BUCKETS: tuple[str, ...] = ("0", "1", "2", "3plus")
EVIDENCE_CARDINALITY_BUCKETS: tuple[str, ...] = ("empty", "single_doc", "multi_doc")
EXPECTED_COVERAGE_BUCKETS: tuple[str, ...] = (
    "no_expected",
    "expected_in_evidence",
    "expected_not_in_evidence",
)
CITATION_REASON_BUCKETS: tuple[str, ...] = (
    "ok",
    "missing_claim_citation",
    "no_claims",
    "missing",
    "other",
)
CLAIM_ERROR_BUCKETS: tuple[str, ...] = (
    "claim_missing_citation",
    "citation_not_in_evidence",
    "claim_text_not_supported_by_citation",
    "expected_claim_doc_mismatch",
    "expected_claim_terms_missing",
    "expected_claim_missing",
    "other",
)
SIGNALS: tuple[str, ...] = (
    "retrieval_fault_signal",
    "low_top_score",
    "citation_missing",
    "unsupported_answer",
)

SPECIFICITY_REGEX = re.compile(r"얼마|구체적|기준은|몇\s*%?|\d+\s*%")


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"eval_summary.json not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("eval_summary.json root must be an object")
    return payload


def source_provenance(path: Path) -> dict[str, Any]:
    """Return a provenance descriptor without leaking external absolute paths."""
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        location = str(resolved_path.relative_to(resolved_root))
        redacted = False
    except ValueError:
        location = f"external_private/{path.name}"
        redacted = True
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return {
        "location": location,
        "location_redacted": redacted,
        "basename": path.name,
        "sha256_12": digest,
    }


def _case_results(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("case_results")
    if not isinstance(raw, list):
        raise ValueError(
            "eval_summary.json::case_results missing or not a list; "
            "regenerate a post-ADR-0059 local real-eval summary."
        )
    return [case for case in raw if isinstance(case, dict)]


def _zero(keys: tuple[str, ...]) -> dict[str, int]:
    return {key: 0 for key in keys}


def _retry_bucket(value: Any) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count == 2:
        return "2"
    return "3plus"


def _cardinality_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count == 2:
        return "2"
    return "3plus"


def _expected_coverage(case: dict[str, Any]) -> str:
    expected = {str(item) for item in case.get("expected_doc_ids") or [] if item}
    evidence = {str(item) for item in case.get("evidence_doc_ids") or [] if item}
    if not expected:
        return "no_expected"
    if expected & evidence:
        return "expected_in_evidence"
    return "expected_not_in_evidence"


def _evidence_cardinality(case: dict[str, Any]) -> str:
    evidence = {str(item) for item in case.get("evidence_doc_ids") or [] if item}
    if not evidence:
        return "empty"
    if len(evidence) == 1:
        return "single_doc"
    return "multi_doc"


def _expected_cardinality(case: dict[str, Any]) -> str:
    expected = {str(item) for item in case.get("expected_doc_ids") or [] if item}
    return _cardinality_bucket(len(expected))


def _specificity_bucket(case: dict[str, Any]) -> str:
    query_text = str(case.get("query") or "")
    return "keyword_hit" if SPECIFICITY_REGEX.search(query_text) else "no_hit"


def _top_score(case: dict[str, Any]) -> float | None:
    chunks = case.get("retrieved_chunks")
    if not isinstance(chunks, list) or not chunks:
        return None
    first = chunks[0]
    if not isinstance(first, dict):
        return None
    value = first.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _p25(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(int(0.25 * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[idx]


def _numeric(case: dict[str, Any], key: str) -> float | None:
    value = case.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _count_list(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _claim_checked_count(case: dict[str, Any]) -> int:
    for key in ("claim_citation_checked", "citation_claim_coverage_denominator"):
        value = case.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _claim_error_codes(case: dict[str, Any]) -> set[str]:
    errors = case.get("claim_citation_errors")
    if not isinstance(errors, list):
        return set()
    codes: set[str] = set()
    allowed = set(CLAIM_ERROR_BUCKETS) - {"other"}
    for error in errors:
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "")
        codes.add(code if code in allowed else "other")
    return codes


def _is_low_top_score(case: dict[str, Any], threshold: float | None) -> bool:
    score = _top_score(case)
    return threshold is not None and score is not None and score <= threshold


def _has_expected_doc_miss(case: dict[str, Any]) -> bool:
    expected = {str(item) for item in case.get("expected_doc_ids") or [] if item}
    evidence = {str(item) for item in case.get("evidence_doc_ids") or [] if item}
    return bool(expected) and not expected.issubset(evidence)


def _has_expected_chunk_miss(case: dict[str, Any]) -> bool:
    expected = {str(item) for item in case.get("gold_chunk_ids") or [] if item}
    retrieved = {str(item) for item in case.get("retrieved_chunk_ids") or [] if item}
    return bool(expected) and not expected.issubset(retrieved)


def _has_partial_or_zero_recall(case: dict[str, Any]) -> bool:
    for key in ("chunk_recall_at_5", "chunk_recall_at_10", "chunk_recall_at_20"):
        value = _numeric(case, key)
        if value is not None:
            return value < 1.0
    return False


def _has_citation_missing(case: dict[str, Any]) -> bool:
    reason = str(case.get("citation_claim_coverage_reason") or "")
    if reason == "missing_claim_citation":
        return True
    if "claim_missing_citation" in _claim_error_codes(case):
        return True
    return _claim_checked_count(case) > 0 and _count_list(case.get("citation")) == 0


def _has_unsupported_answer(case: dict[str, Any]) -> bool:
    alignment = _numeric(case, "claim_citation_alignment")
    if alignment is not None and alignment < 1.0:
        return True
    return bool(_claim_error_codes(case))


def _case_signal_state(case: dict[str, Any], threshold: float | None) -> dict[str, bool]:
    low_score = _is_low_top_score(case, threshold)
    retrieval_fault = any(
        (
            _has_expected_doc_miss(case),
            _has_expected_chunk_miss(case),
            _has_partial_or_zero_recall(case),
            low_score,
        )
    )
    return {
        "retrieval_fault_signal": retrieval_fault,
        "low_top_score": low_score,
        "citation_missing": _has_citation_missing(case),
        "unsupported_answer": _has_unsupported_answer(case),
    }


def _empty_slices() -> dict[str, Any]:
    return {
        "query_type": {key: 0 for key in SAFE_QUERY_TYPES} | {"other": 0},
        "hardcase": {key: 0 for key in SAFE_HARDCASE} | {"untagged": 0, "other": 0},
        "expected_cardinality": _zero(EXPECTED_CARDINALITY_BUCKETS),
        "evidence_cardinality": _zero(EVIDENCE_CARDINALITY_BUCKETS),
        "expected_coverage": _zero(EXPECTED_COVERAGE_BUCKETS),
        "retry_count": _zero(RETRY_BUCKETS),
        "specificity": {"keyword_hit": 0, "no_hit": 0},
    }


def _accumulate_slices(slices: dict[str, Any], case: dict[str, Any]) -> None:
    query_type = str(case.get("query_type") or "")
    slices["query_type"][query_type if query_type in SAFE_QUERY_TYPES else "other"] += 1

    tags = case.get("hardcase_categories") or []
    if not isinstance(tags, list):
        tags = [tags]
    if not tags:
        slices["hardcase"]["untagged"] += 1
    else:
        for tag in tags:
            key = str(tag)
            slices["hardcase"][key if key in SAFE_HARDCASE else "other"] += 1

    slices["expected_cardinality"][_expected_cardinality(case)] += 1
    slices["evidence_cardinality"][_evidence_cardinality(case)] += 1
    slices["expected_coverage"][_expected_coverage(case)] += 1
    slices["retry_count"][_retry_bucket(case.get("retry_count"))] += 1
    slices["specificity"][_specificity_bucket(case)] += 1


def _classified_cases(
    case_results: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], str | None]]:
    return [(case, classify_failure(case)) for case in case_results]


def _failure_counts(
    classified: list[tuple[dict[str, Any], str | None]],
) -> dict[str, int]:
    counts = {category: 0 for category in SAFE_CATEGORIES}
    for _, category in classified:
        if category in counts:
            counts[category] += 1
    return counts


def _failure_by_answerability(
    classified: list[tuple[dict[str, Any], str | None]],
) -> dict[str, dict[str, int]]:
    out = {
        category: {"answerable": 0, "unanswerable": 0}
        for category in SAFE_CATEGORIES
    }
    for case, category in classified:
        if category not in out:
            continue
        bucket = "answerable" if bool(case.get("answerable", True)) else "unanswerable"
        out[category][bucket] += 1
    return out


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _decision(vfn_total: int, overlap: dict[str, Any], slices: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    retrieval_fault_count = int(overlap["retrieval_fault_signal"]["count"])
    expected_in_evidence = int(slices["expected_coverage"]["expected_in_evidence"])
    citation_missing = int(overlap["citation_missing"]["count"])
    unsupported = int(overlap["unsupported_answer"]["count"])

    retrieval_fault_signal_rate = _rate(retrieval_fault_count, vfn_total)
    expected_in_evidence_rate = _rate(expected_in_evidence, vfn_total)
    citation_missing_rate = _rate(citation_missing, vfn_total)
    unsupported_answer_rate = _rate(unsupported, vfn_total)

    retrieval_first = retrieval_fault_signal_rate >= 0.60
    independent = (
        expected_in_evidence_rate >= 0.20
        or citation_missing_rate >= 0.20
        or unsupported_answer_rate >= 0.20
    )
    if retrieval_first and independent:
        label = "mixed"
    elif retrieval_first:
        label = "retrieval_first"
    else:
        label = "independent_verifier_fix"

    return label, {
        "retrieval_fault_signal_rate": retrieval_fault_signal_rate,
        "expected_in_evidence_rate": expected_in_evidence_rate,
        "citation_missing_rate": citation_missing_rate,
        "unsupported_answer_rate": unsupported_answer_rate,
        "retrieval_first_threshold": 0.60,
        "independent_verifier_threshold": 0.20,
    }


def _build_vfn_block(
    classified: list[tuple[dict[str, Any], str | None]],
    low_score_threshold: float | None,
) -> dict[str, Any]:
    vfn_cases = [case for case, category in classified if category == "verifier_false_negative"]
    total = len(vfn_cases)
    slices = _empty_slices()

    overlap = {
        "retrieval_miss_label_overlap": {
            "count": 0,
            "expected_zero_due_to_first_match_wins": True,
        },
        "retrieval_fault_signal": {
            "count": 0,
            "components": {
                "expected_doc_missing": 0,
                "expected_chunk_missing": 0,
                "partial_or_zero_chunk_recall": 0,
                "low_top_score": 0,
            },
        },
        "low_top_score": {
            "count": 0,
            "threshold": (
                round(low_score_threshold, 6)
                if isinstance(low_score_threshold, (int, float))
                else None
            ),
            "buckets": {
                "low_top_score": 0,
                "above_low_top_score": 0,
                "score_missing": 0,
            },
        },
        "citation_missing": {
            "count": 0,
            "citation_claim_coverage_reason": _zero(CITATION_REASON_BUCKETS),
            "empty_citation_count": 0,
        },
        "unsupported_answer": {
            "count": 0,
            "claim_citation_error_codes": _zero(CLAIM_ERROR_BUCKETS),
        },
        "pairwise_intersections": {
            f"{left}+{right}": 0 for left, right in combinations(SIGNALS, 2)
        },
    }

    signal_counts = {signal: 0 for signal in SIGNALS}

    for case in vfn_cases:
        _accumulate_slices(slices, case)
        state = _case_signal_state(case, low_score_threshold)

        if _has_expected_doc_miss(case):
            overlap["retrieval_fault_signal"]["components"]["expected_doc_missing"] += 1
        if _has_expected_chunk_miss(case):
            overlap["retrieval_fault_signal"]["components"]["expected_chunk_missing"] += 1
        if _has_partial_or_zero_recall(case):
            overlap["retrieval_fault_signal"]["components"]["partial_or_zero_chunk_recall"] += 1
        if state["low_top_score"]:
            overlap["retrieval_fault_signal"]["components"]["low_top_score"] += 1

        score = _top_score(case)
        if score is None:
            overlap["low_top_score"]["buckets"]["score_missing"] += 1
        elif state["low_top_score"]:
            overlap["low_top_score"]["buckets"]["low_top_score"] += 1
        else:
            overlap["low_top_score"]["buckets"]["above_low_top_score"] += 1

        reason = str(case.get("citation_claim_coverage_reason") or "missing")
        reason_bucket = reason if reason in CITATION_REASON_BUCKETS else "other"
        overlap["citation_missing"]["citation_claim_coverage_reason"][reason_bucket] += 1
        if _count_list(case.get("citation")) == 0:
            overlap["citation_missing"]["empty_citation_count"] += 1

        for code in _claim_error_codes(case) or set():
            overlap["unsupported_answer"]["claim_citation_error_codes"][code] += 1

        for signal in SIGNALS:
            if state[signal]:
                signal_counts[signal] += 1
        for left, right in combinations(SIGNALS, 2):
            if state[left] and state[right]:
                overlap["pairwise_intersections"][f"{left}+{right}"] += 1

    for signal in SIGNALS:
        if signal == "retrieval_fault_signal":
            overlap[signal]["count"] = signal_counts[signal]
        elif signal in ("low_top_score", "citation_missing", "unsupported_answer"):
            overlap[signal]["count"] = signal_counts[signal]

    decision, decision_inputs = _decision(total, overlap, slices)
    return {
        "total": total,
        "slices": slices,
        "overlap": overlap,
        "decision": decision,
        "decision_inputs": decision_inputs,
    }


def build_aggregate(
    summary: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_results = _case_results(summary)
    classified = _classified_cases(case_results)
    failed_scores = [
        score
        for case, category in classified
        if category is not None
        for score in [_top_score(case)]
        if score is not None
    ]
    threshold = _p25(failed_scores)
    return {
        "schema_version": 1,
        "source": source or dict(DEFAULT_SOURCE_PROVENANCE),
        "num_predictions": int(summary.get("num_predictions") or len(case_results)),
        "failure_category_counts": _failure_counts(classified),
        "failure_category_by_answerability": _failure_by_answerability(classified),
        "verifier_false_negative": _build_vfn_block(classified, threshold),
    }


def _render_table(title: str, values: dict[str, int]) -> list[str]:
    lines = [f"### {title}", "", "| bucket | count |", "|---|---:|"]
    for key, value in values.items():
        lines.append(f"| `{key}` | {value} |")
    lines.append("")
    return lines


def render_markdown(aggregate: dict[str, Any]) -> str:
    vfn = aggregate["verifier_false_negative"]
    overlap = vfn["overlap"]
    total = int(vfn["total"])
    source = aggregate.get("source") if isinstance(aggregate.get("source"), dict) else {}
    source_location = source.get("location") or "reports/real100/eval_summary.json"
    source_hash = source.get("sha256_12")
    lines = [
        "# verifier_false_negative overlap analysis",
        "",
        "Generated by `scripts/render_verifier_false_negative_overlap.py` from "
        f"`{source_location}`. Aggregate-only artifact: no raw "
        "question, answer, evidence, doc_id, chunk_id, case id, or path values.",
        "",
        f"- source_sha256_12: `{source_hash}`",
        f"- num_predictions: `{aggregate['num_predictions']}`",
        f"- verifier_false_negative: `{total}`",
        f"- decision: `{vfn['decision']}`",
        "",
        "## Decision inputs",
        "",
        "| signal | rate |",
        "|---|---:|",
    ]
    for key, value in vfn["decision_inputs"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Failure counts",
            "",
            "| category | count | answerable | unanswerable |",
            "|---|---:|---:|---:|",
        ]
    )
    by_answerability = aggregate["failure_category_by_answerability"]
    for category, count in aggregate["failure_category_counts"].items():
        split = by_answerability[category]
        lines.append(
            f"| `{category}` | {count} | {split['answerable']} | {split['unanswerable']} |"
        )
    lines.extend(
        [
            "",
            "## Overlap",
            "",
            "| signal | count | rate_of_vfn |",
            "|---|---:|---:|",
        ]
    )
    for signal in SIGNALS:
        block = overlap[signal]
        count = int(block["count"]) if isinstance(block, dict) and "count" in block else 0
        lines.append(f"| `{signal}` | {count} | {_rate(count, total)} |")
    label_overlap = overlap["retrieval_miss_label_overlap"]["count"]
    lines.append(
        f"| `retrieval_miss_label_overlap` | {label_overlap} | {_rate(label_overlap, total)} |"
    )
    lines.append("")
    lines.append(
        f"Low top-score threshold: `{overlap['low_top_score']['threshold']}` "
        "(p25 over failed-case top scores; missing scores are bucketed separately)."
    )
    lines.append("")

    lines.extend(_render_table("VFN query_type", vfn["slices"]["query_type"]))
    lines.extend(_render_table("VFN hardcase", vfn["slices"]["hardcase"]))
    lines.extend(_render_table("VFN expected coverage", vfn["slices"]["expected_coverage"]))
    lines.extend(_render_table("Retrieval fault components", overlap["retrieval_fault_signal"]["components"]))
    lines.extend(_render_table("Low top-score buckets", overlap["low_top_score"]["buckets"]))
    lines.extend(_render_table("Citation reasons", overlap["citation_missing"]["citation_claim_coverage_reason"]))
    lines.extend(_render_table("Unsupported answer error codes", overlap["unsupported_answer"]["claim_citation_error_codes"]))
    lines.extend(_render_table("Pairwise intersections", overlap["pairwise_intersections"]))
    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render verifier_false_negative redacted overlap aggregate.",
    )
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = _load_summary(args.summary)
        aggregate = build_aggregate(summary, source_provenance(args.summary))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"Failed to render verifier_false_negative overlap: {exc}", file=sys.stderr)
        return 1
    markdown = render_markdown(aggregate)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(markdown, encoding="utf-8")
    print(f"[OK] Wrote {args.out_json}")
    print(f"[OK] Wrote {args.out_md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
