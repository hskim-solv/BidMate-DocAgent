#!/usr/bin/env python3
"""Render aggregate-only multi-chunk retrieval strategy decision.

This reads only ``multi_chunk_evidence_failures.aggregate.json`` and emits a
committable strategy report. It intentionally does not import or call retrieval,
verifier, prompt, chunking, reranker, answer, or eval runtime code.

ADR 0005 boundary: the input is already aggregate-only, but this renderer still
copies only whitelisted counts and closed enum labels. Unknown labels or raw
case-like fields are ignored instead of propagated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = (
    ROOT / "reports" / "real100" / "multi_chunk_evidence_failures.aggregate.json"
)
DEFAULT_OUT_JSON = (
    ROOT / "reports" / "real100" / "multi_chunk_retrieval_strategy.aggregate.json"
)
DEFAULT_OUT_MD = ROOT / "docs" / "evaluation" / "multi_chunk_retrieval_strategy.md"

RECOMMENDATIONS: tuple[str, ...] = (
    "candidate_pool_expansion",
    "same_doc_neighbor_expansion",
    "section_expansion",
    "query_decomposition",
    "reranker",
    "defer_until_page_metadata_recovery",
)

RETRIEVAL_OUTCOMES: tuple[str, ...] = (
    "all_gold_retrieved",
    "partial_gold_retrieved",
    "no_gold_retrieved",
    "not_observable",
)

EVIDENCE_SPLIT_BUCKETS: tuple[str, ...] = ("same_doc", "multi_doc", "unknown")

SAFE_SOURCE_FORMATS: tuple[str, ...] = (
    "csv",
    "docx",
    "hwp",
    "json",
    "pdf",
    "pptx",
    "txt",
    "xlsx",
    "unknown",
    "other",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _count(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _counts(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    return {key: _count(mapping, key) for key in keys}


def _retrieval_outcome_by_k(payload: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    raw = _mapping(payload.get("retrieval_outcome_by_k"))
    out: dict[str, dict[str, int]] = {}
    for k in ("5", "10", "20"):
        out[k] = _counts(_mapping(raw.get(k)), RETRIEVAL_OUTCOMES)
    return out


def _source_format_counts(raw: Mapping[str, Any]) -> dict[str, int]:
    counts = {key: 0 for key in SAFE_SOURCE_FORMATS}
    for key, value in raw.items():
        bucket = str(key) if str(key) in SAFE_SOURCE_FORMATS else "other"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        counts[bucket] += max(0, int(value))
    return counts


def _structured_block(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "hardcase_table_heavy": _count(raw, "hardcase_table_heavy"),
        "metadata_field_structured": _count(raw, "metadata_field_structured"),
        "case_source_format": _source_format_counts(
            _mapping(raw.get("case_source_format"))
        ),
    }


def _source_summary(payload: Mapping[str, Any], *, input_artifact: str) -> dict[str, Any]:
    source = _mapping(payload.get("source"))
    return {
        "input_artifact": input_artifact,
        "input_schema_version": _count(payload, "schema_version"),
        "source_basename": str(source.get("basename") or ""),
        "source_location_redacted": bool(source.get("location_redacted")),
        "source_sha256_12": str(source.get("sha256_12") or ""),
    }


def input_artifact_label(path: Path) -> str:
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(resolved_root))
    except ValueError:
        return f"external_private/{path.name}"


def _strategy_assessment(
    *,
    population: Mapping[str, int],
    retrieval_by_k: Mapping[str, Mapping[str, int]],
    evidence_split: Mapping[str, int],
    candidate_pool: Mapping[str, int],
    expected_impact: Mapping[str, int],
) -> tuple[str, list[str], dict[str, Any]]:
    multi_cases = population["multi_chunk_gold_cases"]
    top10_failures = population["multi_chunk_top10_evidence_failures"]
    unknown_ratio = _rate(evidence_split["unknown"], multi_cases)
    not_observable_ratio = _rate(
        candidate_pool["not_observable_due_to_depth"], top10_failures
    )
    after_top10 = candidate_pool["missing_gold_seen_after_top10"]
    all_missing_after_top10 = candidate_pool["all_missing_gold_seen_after_top10"]
    pool_or_rerank = expected_impact["pool_or_rerank_candidate"]
    section_candidates = expected_impact["section_expansion_candidate"]
    query_candidates = expected_impact["query_decomposition_candidate"]

    decision_reasons: list[str] = []
    if multi_cases == 0:
        recommendation = "defer_until_page_metadata_recovery"
        decision_reasons.append("no_multi_chunk_population")
    elif unknown_ratio >= 0.5:
        recommendation = "defer_until_page_metadata_recovery"
        decision_reasons.append("evidence_split_unknown_dominant")
    elif not_observable_ratio >= 0.5:
        recommendation = "defer_until_page_metadata_recovery"
        decision_reasons.append("candidate_depth_not_observable_dominant")
    elif all_missing_after_top10 > 0 or pool_or_rerank > 0:
        recommendation = "candidate_pool_expansion"
        decision_reasons.append("missing_gold_observed_after_top10")
    elif section_candidates > 0:
        recommendation = "section_expansion"
        decision_reasons.append("same_doc_partial_gold_signal")
    elif query_candidates > 0:
        recommendation = "query_decomposition"
        decision_reasons.append("multi_doc_gold_signal")
    elif retrieval_by_k["5"]["partial_gold_retrieved"] > 0:
        recommendation = "reranker"
        decision_reasons.append("partial_gold_inside_top5_without_expansion_signal")
    elif evidence_split["same_doc"] > 0:
        recommendation = "same_doc_neighbor_expansion"
        decision_reasons.append("same_doc_gold_signal_without_section_bucket")
    else:
        recommendation = "defer_until_page_metadata_recovery"
        decision_reasons.append("insufficient_aggregate_signal")

    assessments = {
        "candidate_pool_expansion": {
            "likely_help": after_top10 > 0 and recommendation != "defer_until_page_metadata_recovery",
            "missing_gold_seen_after_top10": after_top10,
            "all_missing_gold_seen_after_top10": all_missing_after_top10,
            "not_observable_due_to_depth": candidate_pool[
                "not_observable_due_to_depth"
            ],
            "verdict": (
                "not_supported"
                if after_top10 == 0
                else "supported_but_blocked_by_observability"
                if recommendation == "defer_until_page_metadata_recovery"
                else "supported"
            ),
        },
        "same_doc_neighbor_expansion": {
            "likely_help": False,
            "same_doc_cases": evidence_split["same_doc"],
            "unknown_doc_split_cases": evidence_split["unknown"],
            "verdict": (
                "not_assessable_without_doc_split"
                if evidence_split["unknown"] > 0
                else "not_supported"
            ),
        },
        "section_expansion": {
            "likely_help": section_candidates > 0
            and recommendation != "defer_until_page_metadata_recovery",
            "section_expansion_candidate": section_candidates,
            "verdict": (
                "not_assessable_without_same_doc_split"
                if evidence_split["unknown"] > 0 and section_candidates == 0
                else "supported"
                if section_candidates > 0
                else "not_supported"
            ),
        },
        "query_decomposition": {
            "required": query_candidates > 0
            and recommendation != "defer_until_page_metadata_recovery",
            "query_decomposition_candidate": query_candidates,
            "multi_doc_cases": evidence_split["multi_doc"],
            "verdict": (
                "not_assessable_without_doc_split"
                if evidence_split["unknown"] > 0 and query_candidates == 0
                else "supported"
                if query_candidates > 0
                else "not_supported"
            ),
        },
        "reranker": {
            "required": recommendation == "reranker",
            "pool_or_rerank_candidate": pool_or_rerank,
            "verdict": (
                "insufficient_basis_without_gold_in_candidate_pool"
                if after_top10 == 0
                else "candidate_pool_first"
            ),
        },
    }
    return recommendation, decision_reasons, assessments


def build_strategy_report(
    payload: Mapping[str, Any],
    *,
    input_artifact: str = "reports/real100/multi_chunk_evidence_failures.aggregate.json",
) -> dict[str, Any]:
    population = {
        "num_predictions": _count(_mapping(payload.get("population")), "num_predictions"),
        "multi_chunk_gold_cases": _count(
            _mapping(payload.get("population")), "multi_chunk_gold_cases"
        ),
        "multi_chunk_top10_evidence_failures": _count(
            _mapping(payload.get("population")),
            "multi_chunk_top10_evidence_failures",
        ),
    }
    retrieval_by_k = _retrieval_outcome_by_k(payload)
    evidence_split = _counts(_mapping(payload.get("evidence_split")), EVIDENCE_SPLIT_BUCKETS)
    candidate_pool = _counts(
        _mapping(payload.get("candidate_pool_expansion")),
        (
            "missing_gold_seen_after_top10",
            "all_missing_gold_seen_after_top10",
            "not_observable_due_to_depth",
        ),
    )
    expected_impact = _counts(
        _mapping(payload.get("expected_impact")),
        (
            "pool_or_rerank_candidate",
            "query_decomposition_candidate",
            "section_expansion_candidate",
            "unknown_due_to_limited_depth",
        ),
    )
    structured = _mapping(payload.get("structured_overlap"))
    recommendation, reasons, assessments = _strategy_assessment(
        population=population,
        retrieval_by_k=retrieval_by_k,
        evidence_split=evidence_split,
        candidate_pool=candidate_pool,
        expected_impact=expected_impact,
    )

    return {
        "schema_version": 1,
        "source": _source_summary(payload, input_artifact=input_artifact),
        "recommendation": recommendation,
        "recommendation_set": [recommendation],
        "run_order": "after_page_metadata_recovery",
        "decision_reasons": reasons,
        "population": {
            **population,
            "multi_chunk_top10_evidence_failure_rate": _rate(
                population["multi_chunk_top10_evidence_failures"],
                population["multi_chunk_gold_cases"],
            ),
        },
        "retrieval_outcome_by_k": retrieval_by_k,
        "evidence_split": {
            "counts": evidence_split,
            "ratios": {
                key: _rate(value, population["multi_chunk_gold_cases"])
                for key, value in evidence_split.items()
            },
        },
        "candidate_pool_expansion": candidate_pool,
        "expected_impact": expected_impact,
        "structured_overlap": {
            "multi_chunk_gold_cases": _structured_block(
                _mapping(structured.get("multi_chunk_gold_cases"))
            ),
            "top10_evidence_failures": _structured_block(
                _mapping(structured.get("top10_evidence_failures"))
            ),
        },
        "strategy_assessment": assessments,
        "privacy": {
            "aggregate_only": True,
            "raw_case_fields_copied": False,
            "raw_text_or_identifiers_copied": False,
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    population = _mapping(report.get("population"))
    retrieval = _mapping(report.get("retrieval_outcome_by_k"))
    evidence = _mapping(report.get("evidence_split"))
    split_counts = _mapping(evidence.get("counts"))
    split_ratios = _mapping(evidence.get("ratios"))
    candidate_pool = _mapping(report.get("candidate_pool_expansion"))
    assessment = _mapping(report.get("strategy_assessment"))
    structured = _mapping(_mapping(report.get("structured_overlap")).get("top10_evidence_failures"))
    formats = _mapping(structured.get("case_source_format"))

    recommendation = str(report.get("recommendation") or "")
    reasons = [str(item) for item in report.get("decision_reasons") or []]
    reason_text = ", ".join(reasons) if reasons else "none"

    lines = [
        "# Multi-Chunk Retrieval Strategy Decision",
        "",
        "This report is aggregate-only. It uses counts from "
        "`reports/real100/multi_chunk_evidence_failures.aggregate.json` and does "
        "not include raw questions, answers, document IDs, chunk IDs, paths, "
        "sections, or source text.",
        "",
        "## Recommendation",
        "",
        f"- Recommended next strategy: `{recommendation}`",
        f"- Run order: `{report.get('run_order')}`",
        f"- Decision reasons: `{reason_text}`",
        "",
        "The next retrieval strategy should run after page metadata recovery. "
        "The current aggregate cannot distinguish same-document multi-chunk "
        "failures from multi-document failures because the document split is "
        "unknown for the full multi-chunk population.",
        "",
        "## Aggregate Counts",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Predictions | {population.get('num_predictions', 0)} |",
        f"| Multi-chunk gold cases | {population.get('multi_chunk_gold_cases', 0)} |",
        f"| Top-10 evidence failures | {population.get('multi_chunk_top10_evidence_failures', 0)} |",
        f"| Top-10 evidence failure rate | {population.get('multi_chunk_top10_evidence_failure_rate', 0)} |",
        "",
        "## Retrieval Outcomes",
        "",
        "| k | all | partial | none | not observable |",
        "|---:|---:|---:|---:|---:|",
    ]
    for k in ("5", "10", "20"):
        row = _mapping(retrieval.get(k))
        lines.append(
            f"| {k} | {row.get('all_gold_retrieved', 0)} | "
            f"{row.get('partial_gold_retrieved', 0)} | "
            f"{row.get('no_gold_retrieved', 0)} | "
            f"{row.get('not_observable', 0)} |"
        )

    lines.extend(
        [
            "",
            "## Evidence Split",
            "",
            "| Bucket | Count | Ratio |",
            "|---|---:|---:|",
        ]
    )
    for bucket in EVIDENCE_SPLIT_BUCKETS:
        lines.append(
            f"| `{bucket}` | {split_counts.get(bucket, 0)} | "
            f"{split_ratios.get(bucket, 0)} |"
        )

    lines.extend(
        [
            "",
            "## Strategy Assessment",
            "",
            "| Strategy | Aggregate verdict | Key count |",
            "|---|---|---:|",
        ]
    )
    strategy_rows = [
        (
            "candidate_pool_expansion",
            _mapping(assessment.get("candidate_pool_expansion")).get("verdict", ""),
            candidate_pool.get("missing_gold_seen_after_top10", 0),
        ),
        (
            "same_doc_neighbor_expansion",
            _mapping(assessment.get("same_doc_neighbor_expansion")).get("verdict", ""),
            split_counts.get("same_doc", 0),
        ),
        (
            "section_expansion",
            _mapping(assessment.get("section_expansion")).get("verdict", ""),
            _mapping(assessment.get("section_expansion")).get(
                "section_expansion_candidate", 0
            ),
        ),
        (
            "query_decomposition",
            _mapping(assessment.get("query_decomposition")).get("verdict", ""),
            _mapping(assessment.get("query_decomposition")).get(
                "query_decomposition_candidate", 0
            ),
        ),
        (
            "reranker",
            _mapping(assessment.get("reranker")).get("verdict", ""),
            _mapping(assessment.get("reranker")).get("pool_or_rerank_candidate", 0),
        ),
    ]
    for strategy, verdict, count in strategy_rows:
        lines.append(f"| `{strategy}` | `{verdict}` | {count} |")

    lines.extend(
        [
            "",
            "## Structured-Data Overlap",
            "",
            "| Signal | Count |",
            "|---|---:|",
            f"| table-heavy top-10 failures | {structured.get('hardcase_table_heavy', 0)} |",
            f"| structured metadata-field top-10 failures | {structured.get('metadata_field_structured', 0)} |",
            f"| source format `other` top-10 failures | {formats.get('other', 0)} |",
            "",
            "## Boundary",
            "",
            "- No retrieval, verifier, prompt, chunking, reranker, answer generation, or runtime behavior changes are implied by this report.",
            "- The recommendation is based on aggregate counts only.",
            "- Re-run this report after page metadata recovery before choosing a concrete retrieval change.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render aggregate-only multi-chunk retrieval strategy decision.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input aggregate path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_OUT_JSON,
        help=f"Output aggregate JSON path (default: {DEFAULT_OUT_JSON})",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_OUT_MD,
        help=f"Output markdown path (default: {DEFAULT_OUT_MD})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        payload = _load_json(args.input)
        report = build_strategy_report(
            payload,
            input_artifact=input_artifact_label(args.input),
        )
        if report["recommendation"] not in RECOMMENDATIONS:
            raise ValueError(f"invalid recommendation: {report['recommendation']}")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to render multi-chunk retrieval strategy: {exc}", file=sys.stderr)
        return 1

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"[OK] Wrote {args.out_json}")
    print(f"[OK] Wrote {args.out_md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
