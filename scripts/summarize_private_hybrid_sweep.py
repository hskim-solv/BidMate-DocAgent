#!/usr/bin/env python3
"""Summarize private hybrid sweep aggregates into a public-safe decision.

Reads ``reports/retrieval/hybrid_sweep_*/aggregate.json`` and writes a stable
aggregate-only markdown + JSON pair. This is a read-only measurement consumer:
it does not import retrieval runtime code or change retrieval/verifier behavior.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_private_hybrid_sweep import (  # noqa: E402
    ABSOLUTE_LOCAL_PATH_RE,
    FORBIDDEN_KEYS,
    FORBIDDEN_PATH_FRAGMENTS,
    assert_rendered_output_privacy_safe,
    render_output_path,
)

DEFAULT_OUT_MD = ROOT / "reports" / "retrieval" / "hybrid_sweep_summary.md"
DEFAULT_OUT_JSON = ROOT / "reports" / "retrieval" / "hybrid_sweep_summary.aggregate.json"

MATERIAL_RECALL_DELTA = 0.005
METRIC_REGRESSION_TOLERANCE = 0.001
LATENCY_REGRESSION_RATIO = 0.05
LATENCY_REGRESSION_MS = 10.0

FINAL_DECISIONS = {
    "promote selected hybrid variant",
    "run reranker after hybrid",
    "keep dense baseline and abandon hybrid for now",
    "run metadata/page-aware recovery first",
    "mark hybrid as failed experiment",
}

_PATH_LIKE_RE = re.compile(r"(^|[\s:=`'\"])(?:\.{0,2}/|[A-Za-z]:[\\/]|[^ \t\n]+[\\/][^ \t\n]+)")


@dataclass(frozen=True)
class NormalizedMetrics:
    recall_at_5: float | None
    recall_at_10: float | None
    mrr_at_5: float | None
    ndcg_at_5: float | None
    citation_value: float | None
    citation_metric: str | None
    citation_guardrail_rates: dict[str, float]
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    retrieval_miss_count: int | None
    retrieval_miss_rate: float | None
    retrieval_miss_denominator: int | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aggregate",
        default=None,
        help="Input aggregate.json. Defaults to newest reports/retrieval/hybrid_sweep_*/aggregate.json.",
    )
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    return parser.parse_args(argv)


def newest_aggregate() -> Path:
    candidates = sorted(
        (ROOT / "reports" / "retrieval").glob("hybrid_sweep_*/aggregate.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            "No hybrid sweep aggregate found under reports/retrieval/hybrid_sweep_*/aggregate.json"
        )
    return candidates[0]


def load_aggregate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("hybrid sweep aggregate root must be an object")
    return payload


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _metric(metrics: dict[str, Any], *aliases: str) -> float | None:
    for key in aliases:
        if key not in metrics:
            continue
        value = metrics.get(key)
        direct = _number(value)
        if direct is not None:
            return direct
        if isinstance(value, dict):
            for nested_key in ("mean", "rate", "value"):
                nested = _number(value.get(nested_key))
                if nested is not None:
                    return nested
    return None


def _latency(metrics: dict[str, Any]) -> tuple[float | None, float | None]:
    block = metrics.get("latency_ms")
    if not isinstance(block, dict):
        block = metrics.get("latency")
    if not isinstance(block, dict):
        return (None, None)
    p50 = _number(block.get("p50"))
    if p50 is None:
        p50 = _number(block.get("p50_ms"))
    p95 = _number(block.get("p95"))
    if p95 is None:
        p95 = _number(block.get("p95_ms"))
    return (p50, p95)


def _citation_guardrail_rates(metrics: dict[str, Any]) -> dict[str, float]:
    block = metrics.get("citation_chunk_guardrail")
    if not isinstance(block, dict):
        return {}
    out: dict[str, float] = {}
    for key in sorted(block):
        value = block.get(key)
        rate = None
        if isinstance(value, dict):
            rate = _number(value.get("rate"))
        else:
            rate = _number(value)
        if rate is not None:
            out[str(key)] = rate
    return out


def _retrieval_miss(metrics: dict[str, Any]) -> tuple[int | None, float | None, int | None]:
    if "retrieval_miss" not in metrics:
        return (None, None, None)
    value = metrics.get("retrieval_miss")
    if isinstance(value, dict):
        count_raw = value.get("count")
        denom_raw = value.get("denominator")
        count = int(count_raw) if isinstance(count_raw, int) and not isinstance(count_raw, bool) else None
        denominator = (
            int(denom_raw)
            if isinstance(denom_raw, int) and not isinstance(denom_raw, bool)
            else None
        )
        return (count, _number(value.get("rate")), denominator)
    if isinstance(value, int) and not isinstance(value, bool):
        return (int(value), None, None)
    return (None, None, None)


def normalize_metrics(variant: dict[str, Any]) -> NormalizedMetrics:
    metrics = variant.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    citation_metric = None
    citation_value = _metric(metrics, "citation_precision")
    if citation_value is not None:
        citation_metric = "citation_precision"
    else:
        citation_value = _metric(metrics, "citation_accuracy")
        if citation_value is not None:
            citation_metric = "citation_accuracy"
    p50, p95 = _latency(metrics)
    miss_count, miss_rate, miss_denominator = _retrieval_miss(metrics)
    return NormalizedMetrics(
        recall_at_5=_metric(metrics, "recall_at_5", "chunk_recall_at_5", "Recall@5", "chunk_recall@5"),
        recall_at_10=_metric(metrics, "recall_at_10", "chunk_recall_at_10", "Recall@10", "chunk_recall@10"),
        mrr_at_5=_metric(metrics, "mrr_at_5", "chunk_mrr_at_5", "MRR@5"),
        ndcg_at_5=_metric(metrics, "ndcg_at_5", "chunk_ndcg_at_5", "nDCG@5", "ndcg@5"),
        citation_value=citation_value,
        citation_metric=citation_metric,
        citation_guardrail_rates=_citation_guardrail_rates(metrics),
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        retrieval_miss_count=miss_count,
        retrieval_miss_rate=miss_rate,
        retrieval_miss_denominator=miss_denominator,
    )


def _params(variant: dict[str, Any]) -> dict[str, Any]:
    params = variant.get("parameters")
    return params if isinstance(params, dict) else {}


def _is_hybrid(variant: dict[str, Any]) -> bool:
    name = str(variant.get("name") or "")
    params = _params(variant)
    return name.startswith("hybrid_") or params.get("retrieval_backend") == "hybrid"


def _variant_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    params = _params(row.get("variant") or {})
    return (
        int(params.get("rrf_k") or 0),
        int(params.get("dense_pool") or 0),
        int(params.get("bm25_pool") or 0),
        str(row.get("name") or ""),
    )


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _latency_regressed(candidate: float | None, baseline: float | None) -> bool:
    if candidate is None or baseline is None:
        return False
    tolerance = max(LATENCY_REGRESSION_MS, abs(baseline) * LATENCY_REGRESSION_RATIO)
    return candidate > baseline + tolerance


def _citation_comparison(candidate: NormalizedMetrics, baseline: NormalizedMetrics) -> tuple[str | None, float | None, bool]:
    if (
        candidate.citation_value is not None
        and baseline.citation_value is not None
        and candidate.citation_metric == baseline.citation_metric
    ):
        delta = candidate.citation_value - baseline.citation_value
        return (candidate.citation_metric, delta, delta < -METRIC_REGRESSION_TOLERANCE)

    shared = sorted(set(candidate.citation_guardrail_rates) & set(baseline.citation_guardrail_rates))
    if shared:
        max_delta = max(
            candidate.citation_guardrail_rates[key] - baseline.citation_guardrail_rates[key]
            for key in shared
        )
        return ("citation_chunk_guardrail", max_delta, max_delta > METRIC_REGRESSION_TOLERANCE)

    return (None, None, False)


def _retrieval_miss_delta(candidate: NormalizedMetrics, baseline: NormalizedMetrics) -> int | float | None:
    if candidate.retrieval_miss_count is None or baseline.retrieval_miss_count is None:
        return None
    if (
        candidate.retrieval_miss_denominator is not None
        and baseline.retrieval_miss_denominator is not None
        and candidate.retrieval_miss_denominator == baseline.retrieval_miss_denominator
    ):
        return candidate.retrieval_miss_count - baseline.retrieval_miss_count
    if candidate.retrieval_miss_rate is not None and baseline.retrieval_miss_rate is not None:
        return candidate.retrieval_miss_rate - baseline.retrieval_miss_rate
    return None


def classify_variant(variant: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    candidate_metrics = normalize_metrics(variant)
    baseline_metrics = normalize_metrics(baseline)

    required: list[tuple[str, Any]] = [
        ("recall_at_5", candidate_metrics.recall_at_5),
        ("recall_at_10", candidate_metrics.recall_at_10),
        ("mrr_at_5", candidate_metrics.mrr_at_5),
        ("ndcg_at_5", candidate_metrics.ndcg_at_5),
        ("latency_p50_ms", candidate_metrics.latency_p50_ms),
        ("latency_p95_ms", candidate_metrics.latency_p95_ms),
        ("baseline_recall_at_5", baseline_metrics.recall_at_5),
        ("baseline_recall_at_10", baseline_metrics.recall_at_10),
        ("baseline_mrr_at_5", baseline_metrics.mrr_at_5),
        ("baseline_ndcg_at_5", baseline_metrics.ndcg_at_5),
        ("baseline_latency_p50_ms", baseline_metrics.latency_p50_ms),
        ("baseline_latency_p95_ms", baseline_metrics.latency_p95_ms),
    ]
    missing = [key for key, value in required if value is None]
    citation_metric, citation_delta, citation_regression = _citation_comparison(
        candidate_metrics, baseline_metrics
    )
    if citation_metric is None:
        missing.append("citation")

    recall5_delta = _delta(candidate_metrics.recall_at_5, baseline_metrics.recall_at_5)
    recall10_delta = _delta(candidate_metrics.recall_at_10, baseline_metrics.recall_at_10)
    mrr5_delta = _delta(candidate_metrics.mrr_at_5, baseline_metrics.mrr_at_5)
    ndcg5_delta = _delta(candidate_metrics.ndcg_at_5, baseline_metrics.ndcg_at_5)
    latency_p50_delta = _delta(candidate_metrics.latency_p50_ms, baseline_metrics.latency_p50_ms)
    latency_p95_delta = _delta(candidate_metrics.latency_p95_ms, baseline_metrics.latency_p95_ms)

    if missing:
        classifications = ["failed_experiment"]
        primary = "failed_experiment"
    else:
        recall_gain = max(recall5_delta or 0.0, recall10_delta or 0.0) >= MATERIAL_RECALL_DELTA
        ranking_regression = (
            (mrr5_delta or 0.0) < -METRIC_REGRESSION_TOLERANCE
            or (ndcg5_delta or 0.0) < -METRIC_REGRESSION_TOLERANCE
        )
        latency_regression = _latency_regressed(
            candidate_metrics.latency_p50_ms, baseline_metrics.latency_p50_ms
        ) or _latency_regressed(candidate_metrics.latency_p95_ms, baseline_metrics.latency_p95_ms)

        classifications = []
        if ranking_regression:
            classifications.append("ranking_regression")
        if citation_regression:
            classifications.append("citation_regression")
        if latency_regression:
            classifications.append("latency_regression")

        if recall_gain and not classifications:
            classifications.insert(0, "winner_found")
            primary = "winner_found"
        elif recall_gain:
            classifications.insert(0, "recall_only_gain")
            primary = "recall_only_gain"
        elif classifications:
            primary = classifications[0]
        else:
            classifications.append("no_material_change")
            primary = "no_material_change"

    params = _params(variant)
    return {
        "name": str(variant.get("name") or ""),
        "variant": variant,
        "parameters": {
            "rrf_k": params.get("rrf_k"),
            "dense_pool": params.get("dense_pool"),
            "bm25_pool": params.get("bm25_pool"),
            "top_k": params.get("top_k"),
        },
        "metrics": {
            "recall_at_5": candidate_metrics.recall_at_5,
            "recall_at_10": candidate_metrics.recall_at_10,
            "mrr_at_5": candidate_metrics.mrr_at_5,
            "ndcg_at_5": candidate_metrics.ndcg_at_5,
            "citation_metric": citation_metric or candidate_metrics.citation_metric,
            "citation_value": candidate_metrics.citation_value,
            "latency_p50_ms": candidate_metrics.latency_p50_ms,
            "latency_p95_ms": candidate_metrics.latency_p95_ms,
            "retrieval_miss_count": candidate_metrics.retrieval_miss_count,
            "retrieval_miss_rate": candidate_metrics.retrieval_miss_rate,
            "retrieval_miss_denominator": candidate_metrics.retrieval_miss_denominator,
        },
        "deltas_vs_dense": {
            "recall_at_5": recall5_delta,
            "recall_at_10": recall10_delta,
            "mrr_at_5": mrr5_delta,
            "ndcg_at_5": ndcg5_delta,
            "citation": citation_delta,
            "latency_p50_ms": latency_p50_delta,
            "latency_p95_ms": latency_p95_delta,
            "retrieval_miss": _retrieval_miss_delta(candidate_metrics, baseline_metrics),
        },
        "primary_classification": primary,
        "classifications": classifications,
        "missing_metrics": missing,
    }


def _candidate_score(row: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
    deltas = row.get("deltas_vs_dense") or {}
    metrics = row.get("metrics") or {}
    recall_gain = max(float(deltas.get("recall_at_5") or 0.0), float(deltas.get("recall_at_10") or 0.0))
    ranking_delta = min(float(deltas.get("mrr_at_5") or 0.0), float(deltas.get("ndcg_at_5") or 0.0))
    citation_delta = float(deltas.get("citation") or 0.0)
    if metrics.get("citation_metric") == "citation_chunk_guardrail":
        citation_delta = -citation_delta
    latency = float(metrics.get("latency_p95_ms") or 0.0)
    return (
        recall_gain,
        ranking_delta,
        citation_delta,
        -latency,
        float(metrics.get("recall_at_10") or 0.0),
        str(row.get("name") or ""),
    )


def build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    assert_summary_privacy_safe(payload)
    variants = payload.get("variants")
    if not isinstance(variants, list):
        raise ValueError("aggregate payload must contain variants[]")
    baseline_name = str((payload.get("sweep") or {}).get("baseline") or "full_dense_top20")
    baseline = next(
        (row for row in variants if isinstance(row, dict) and row.get("name") == baseline_name),
        None,
    )
    if baseline is None:
        baseline = next(
            (
                row
                for row in variants
                if isinstance(row, dict)
                and str(row.get("name") or "").startswith("full_dense")
            ),
            None,
        )
    if baseline is None:
        raise ValueError("dense baseline variant not found")

    candidate_rows = [
        classify_variant(row, baseline)
        for row in variants
        if isinstance(row, dict) and row is not baseline and _is_hybrid(row)
    ]
    candidate_rows.sort(key=_variant_sort_key)
    winners = [row for row in candidate_rows if row["primary_classification"] == "winner_found"]
    failed = [row for row in candidate_rows if row["primary_classification"] == "failed_experiment"]
    if winners:
        selected = max(winners, key=_candidate_score)
        final_decision = "promote selected hybrid variant"
    elif candidate_rows and len(failed) == len(candidate_rows):
        selected = None
        final_decision = "mark hybrid as failed experiment"
    else:
        selected = max(
            [row for row in candidate_rows if row["primary_classification"] != "failed_experiment"],
            key=_candidate_score,
            default=None,
        )
        final_decision = "keep dense baseline and abandon hybrid for now"

    assert final_decision in FINAL_DECISIONS
    baseline_metrics = normalize_metrics(baseline)
    summary = {
        "schema_version": 1,
        "artifact_type": "private_hybrid_sweep_decision_summary",
        "privacy_boundary": "aggregate_only_no_raw_content_or_identifiers",
        "reference": {
            "dense_baseline": str(baseline.get("name") or baseline_name),
            "pr_1448": {
                "decision": "NO-GO",
                "rule": "NO-GO unless a sweep candidate is classified as winner_found",
            },
        },
        "thresholds": {
            "material_recall_delta": MATERIAL_RECALL_DELTA,
            "metric_regression_tolerance": METRIC_REGRESSION_TOLERANCE,
            "latency_regression_ratio": LATENCY_REGRESSION_RATIO,
            "latency_regression_ms": LATENCY_REGRESSION_MS,
        },
        "baseline": {
            "name": str(baseline.get("name") or baseline_name),
            "metrics": {
                "recall_at_5": baseline_metrics.recall_at_5,
                "recall_at_10": baseline_metrics.recall_at_10,
                "mrr_at_5": baseline_metrics.mrr_at_5,
                "ndcg_at_5": baseline_metrics.ndcg_at_5,
                "citation_metric": baseline_metrics.citation_metric,
                "citation_value": baseline_metrics.citation_value,
                "latency_p50_ms": baseline_metrics.latency_p50_ms,
                "latency_p95_ms": baseline_metrics.latency_p95_ms,
                "retrieval_miss_count": baseline_metrics.retrieval_miss_count,
                "retrieval_miss_rate": baseline_metrics.retrieval_miss_rate,
                "retrieval_miss_denominator": baseline_metrics.retrieval_miss_denominator,
            },
        },
        "decision": {
            "final": final_decision,
            "selected_variant": selected.get("name") if selected else None,
            "winner_found": bool(winners),
            "candidate_count": len(candidate_rows),
            "failed_candidate_count": len(failed),
        },
        "variants": [
            {
                key: value
                for key, value in row.items()
                if key != "variant"
            }
            for row in candidate_rows
        ],
        "notes": [
            "Recall@10-only gains are insufficient when ranking, citation, or latency guardrails regress.",
            "#1448 remains NO-GO unless a sweep winner is found.",
        ],
    }
    assert_summary_privacy_safe(summary)
    return summary


def _fmt(value: Any, *, percent: bool = False, signed: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if percent:
            val = value * 100
            prefix = "+" if signed and val > 0 else ""
            return f"{prefix}{val:.2f}pp" if signed else f"{val:.2f}%"
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:.3f}"
    return str(value)


def _fmt_ms(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:.1f}"
    return str(value)


def _fmt_count(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    decision = summary["decision"]
    baseline = summary["baseline"]
    lines = [
        "# Hybrid Sweep Decision",
        "",
        "This report is aggregate-only. It contains no raw questions, answers, evidence text, document identifiers, chunk identifiers, filenames, or local paths.",
        "",
        "## Decision",
        "",
        f"- Final decision: `{decision['final']}`",
        f"- Selected variant: `{decision['selected_variant'] or '-'}`",
        "- #1448 reference: `NO-GO unless a sweep candidate is classified as winner_found`",
        "",
        "Recall@10-only gains are insufficient when MRR@5, nDCG@5, citation, or latency regresses because the system must retrieve the right evidence early, cite it correctly, and stay within the existing latency envelope.",
        "",
        "## Dense Baseline",
        "",
        "| Variant | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Citation | p50 ms | p95 ms | retrieval_miss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    base_metrics = baseline["metrics"]
    lines.append(
        "| {name} | {r5} | {r10} | {mrr} | {ndcg} | {citation} | {p50} | {p95} | {miss} |".format(
            name=baseline["name"],
            r5=_fmt(base_metrics.get("recall_at_5")),
            r10=_fmt(base_metrics.get("recall_at_10")),
            mrr=_fmt(base_metrics.get("mrr_at_5")),
            ndcg=_fmt(base_metrics.get("ndcg_at_5")),
            citation=_fmt(base_metrics.get("citation_value")),
            p50=_fmt_ms(base_metrics.get("latency_p50_ms")),
            p95=_fmt_ms(base_metrics.get("latency_p95_ms")),
            miss=_fmt_count(base_metrics.get("retrieval_miss_count")),
        )
    )
    lines.extend(
        [
            "",
            "## Hybrid Variants",
            "",
            "| Variant | k | Dense pool | BM25 pool | dR@5 | dR@10 | dMRR@5 | dnDCG@5 | dCitation | dP50 ms | dP95 ms | dMiss | Classification |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["variants"]:
        params = row["parameters"]
        deltas = row["deltas_vs_dense"]
        lines.append(
            "| {name} | {k} | {dense} | {bm25} | {dr5} | {dr10} | {dmrr} | {dndcg} | {dcit} | {dp50} | {dp95} | {dmiss} | {cls} |".format(
                name=row["name"],
                k=_fmt_count(params.get("rrf_k")),
                dense=_fmt_count(params.get("dense_pool")),
                bm25=_fmt_count(params.get("bm25_pool")),
                dr5=_fmt(deltas.get("recall_at_5"), signed=True),
                dr10=_fmt(deltas.get("recall_at_10"), signed=True),
                dmrr=_fmt(deltas.get("mrr_at_5"), signed=True),
                dndcg=_fmt(deltas.get("ndcg_at_5"), signed=True),
                dcit=_fmt(deltas.get("citation"), signed=True),
                dp50=_fmt_ms(deltas.get("latency_p50_ms"), signed=True),
                dp95=_fmt_ms(deltas.get("latency_p95_ms"), signed=True),
                dmiss=_fmt_count(deltas.get("retrieval_miss")),
                cls=", ".join(row["classifications"]),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `winner_found` requires a material Recall@5 or Recall@10 gain and no MRR@5, nDCG@5, citation, or latency regression.",
            "- Missing required metrics are classified as `failed_experiment`; missing `retrieval_miss` is displayed as `-`, not zero.",
            "- Timestamped sweep outputs remain local and gitignored.",
            "",
        ]
    )
    rendered = "\n".join(lines)
    assert_summary_text_privacy_safe(rendered)
    return rendered


def assert_summary_privacy_safe(obj: Any) -> None:
    hits: list[str] = []

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                if key_text.lower() in FORBIDDEN_KEYS:
                    hits.append(f"{trail}.{key_text}")
                if "/" in key_text or "\\" in key_text or ":" in key_text:
                    hits.append(f"{trail}.{key_text}:path_like_key")
                walk(value, f"{trail}.{key_text}")
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{trail}[{idx}]")
        elif isinstance(node, str):
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                if fragment in node:
                    hits.append(f"{trail}:private_path_fragment")
                    break
            if ABSOLUTE_LOCAL_PATH_RE.search(node) or _PATH_LIKE_RE.search(node):
                hits.append(f"{trail}:path_like_value")

    walk(obj, "$")
    if hits:
        raise ValueError("summary artifact failed privacy guard: " + ", ".join(hits[:20]))


def assert_summary_text_privacy_safe(text: str) -> None:
    hits = [fragment for fragment in FORBIDDEN_PATH_FRAGMENTS if fragment in text]
    if ABSOLUTE_LOCAL_PATH_RE.search(text):
        hits.append("absolute_local_path")
    if hits:
        raise ValueError("summary markdown failed privacy guard: " + ", ".join(sorted(set(hits))))


def write_summary(summary: dict[str, Any], out_md: Path, out_json: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    assert_summary_privacy_safe(summary)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_markdown(summary), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    aggregate_path = Path(args.aggregate) if args.aggregate else newest_aggregate()
    if not aggregate_path.is_absolute():
        aggregate_path = ROOT / aggregate_path
    payload = load_aggregate(aggregate_path)
    summary = build_summary(payload)
    out_md = Path(args.out_md)
    out_json = Path(args.out_json)
    if not out_md.is_absolute():
        out_md = ROOT / out_md
    if not out_json.is_absolute():
        out_json = ROOT / out_json
    write_summary(summary, out_md, out_json)
    message = (
        f"[OK] hybrid sweep summary written: {render_output_path(out_md)} "
        f"and {render_output_path(out_json)}"
    )
    assert_rendered_output_privacy_safe(message)
    print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
