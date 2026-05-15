#!/usr/bin/env python3
"""RAG pipeline EDA generator (7-axis profile).

Sibling to ``scripts/eda_real100.py`` (corpus-side 4-axis profile). This
script profiles **pipeline dynamics** observed during eval: how retrieval,
reranking, verification, answer synthesis, and latency decompose across
``eval_summary.json::case_results``.

Reads:
  - reports/eval_summary.json          (case_results — required)
  - reports/real100/baseline.aggregate.json     [optional] aggregate context

Writes:
  - reports/rag_pipeline.md            (markdown report)
  - reports/rag_pipeline.aggregate.json (machine-readable dump)
  - reports/figures/real100_rag_*.png|.svg     (7 figures, matplotlib optional)

ADR 0005 boundary: case-level data (case.id, query, answer, evidence text,
retrieved_chunk_ids, gold_chunk_ids, metadata_selected_doc_ids,
expected_doc_ids, etc.) is read for *numeric aggregation only*. None of
those raw strings or IDs is ever written into rendered md/json — only
means, percentiles, counts, ratios, and Pearson scalars cross the boundary.
The defensive ``_PRIVATE_KEYS`` filter strips internal raw distribution
lists before JSON serialization.

Usage:
    python scripts/rag_pipeline_eda.py \\
        --eval-summary reports/eval_summary.json \\
        --baseline reports/real100/baseline.aggregate.json \\
        --out-md reports/rag_pipeline.md \\
        --out-json reports/rag_pipeline.aggregate.json \\
        --figures-dir reports/figures \\
        --seed 0
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

CONFIDENCE_BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
RECALL_HI_THRESHOLD = 0.5
CITATION_HI_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_eval_summary(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _floats(xs: list[Any]) -> list[float]:
    return [float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]


def _percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def _distribution(xs: list[float]) -> dict[str, float | int | None]:
    vals = _floats(xs)
    return {
        "n": len(vals),
        "p10": _percentile(vals, 0.10),
        "p50": _percentile(vals, 0.50),
        "p90": _percentile(vals, 0.90),
        "p95": _percentile(vals, 0.95),
        "mean": mean(vals) if vals else None,
    }


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs = xs[:n]
    ys = ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(dx2 * dy2)
    if denom == 0:
        return None
    return num / denom


def _fmt_num(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return "—"
        return f"{v:.{digits}f}" if isinstance(v, float) else str(v)
    return str(v)


def _fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{int(v):,}"
    return str(v)


def _fmt_pct(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v * 100:.{digits}f}%"
    return str(v)


def _safe_div(a: float, b: float) -> float | None:
    return (a / b) if b else None


# ---------------------------------------------------------------------------
# Axis 1 — Retrieval efficiency
# ---------------------------------------------------------------------------

def axis1_retrieval_efficiency(cases: list[dict]) -> dict[str, Any]:
    recall_ks = (5, 10, 20)
    recall: dict[str, dict[str, Any]] = {}
    for k in recall_ks:
        recall[f"at_{k}"] = _distribution([c.get(f"chunk_recall_at_{k}") for c in cases])
    mrr = _distribution([c.get("chunk_mrr") for c in cases])
    ndcg = {
        "at_10": _distribution([c.get("chunk_ndcg_at_10") for c in cases]),
        "at_20": _distribution([c.get("chunk_ndcg_at_20") for c in cases]),
    }
    top_k_hist = Counter(int(c.get("selected_top_k") or 0) for c in cases if c.get("selected_top_k"))
    candidate_pool = _distribution([c.get("metadata_candidate_count") for c in cases])
    n_with_gold = sum(1 for c in cases if c.get("gold_chunk_ids"))
    return {
        "n_cases": len(cases),
        "n_cases_with_gold_chunks": n_with_gold,
        "recall": recall,
        "mrr": mrr,
        "ndcg": ndcg,
        "selected_top_k_histogram": dict(sorted(top_k_hist.items())),
        "metadata_candidate_pool": candidate_pool,
    }


# ---------------------------------------------------------------------------
# Axis 2 — Reranker contribution
# ---------------------------------------------------------------------------

def axis2_reranker_contribution(cases: list[dict]) -> dict[str, Any]:
    deltas_mrr = _floats([c.get("rerank_delta_mrr") for c in cases])
    deltas_ndcg = _floats([c.get("rerank_delta_ndcg_at_10") for c in cases])

    def _bucket(deltas: list[float]) -> dict[str, Any]:
        n = len(deltas)
        if n == 0:
            return {
                "n_cases_with_rerank": 0,
                "n_improved": 0,
                "n_unchanged": 0,
                "n_regressed": 0,
                "mean_delta": None,
                "p50_delta": None,
                "share_improved": None,
                "share_unchanged": None,
                "share_regressed": None,
            }
        n_imp = sum(1 for d in deltas if d > 1e-9)
        n_reg = sum(1 for d in deltas if d < -1e-9)
        n_unc = n - n_imp - n_reg
        return {
            "n_cases_with_rerank": n,
            "n_improved": n_imp,
            "n_unchanged": n_unc,
            "n_regressed": n_reg,
            "mean_delta": sum(deltas) / n,
            "p50_delta": _percentile(deltas, 0.5),
            "share_improved": n_imp / n,
            "share_unchanged": n_unc / n,
            "share_regressed": n_reg / n,
        }

    return {
        "rerank_delta_mrr": _bucket(deltas_mrr),
        "rerank_delta_ndcg_at_10": _bucket(deltas_ndcg),
        "_raw_delta_mrr": deltas_mrr,
    }


# ---------------------------------------------------------------------------
# Axis 3 — Verification & retry
# ---------------------------------------------------------------------------

def _retry_reason_prefix(reason: str) -> str:
    """Strip dynamic context from a retry reason for ADR 0005 boundary safety.

    Reasons such as ``missing_comparison_doc:<doc_id>,<agency>`` embed
    private identifiers; keep only the enum prefix before the first ``:``.
    """
    if not isinstance(reason, str):
        return ""
    return reason.split(":", 1)[0]


def axis3_verification_retry(cases: list[dict], baseline: dict | None) -> dict[str, Any]:
    verify_outcomes = [c.get("last_attempt_verified") for c in cases]
    verified = sum(1 for v in verify_outcomes if v is True)
    not_verified = sum(1 for v in verify_outcomes if v is False)
    null_attempts = sum(1 for v in verify_outcomes if v is None)
    n = len(cases)
    verify_rate = _safe_div(verified, verified + not_verified)

    retry_counts = [int(c.get("retry_count") or 0) for c in cases]
    attempts_dist = Counter()
    for r in retry_counts:
        if r == 0:
            attempts_dist["1"] += 1
        elif r == 1:
            attempts_dist["2"] += 1
        else:
            attempts_dist["3+"] += 1

    reason_counter: Counter[str] = Counter()
    for c in cases:
        for reason in c.get("retry_trigger_reasons") or []:
            if isinstance(reason, str):
                reason_counter[_retry_reason_prefix(reason)] += 1

    baseline_block = (baseline or {}).get("retry_effectiveness") or {}
    baseline_reason_counts_raw = (baseline or {}).get("retry_reason_counts") or {}
    baseline_reason_counts: dict[str, int] = {}
    for k, v in baseline_reason_counts_raw.items():
        baseline_reason_counts[_retry_reason_prefix(k)] = baseline_reason_counts.get(_retry_reason_prefix(k), 0) + int(v or 0)
    return {
        "n_cases": n,
        "verify_rate": verify_rate,
        "verify_breakdown": {
            "verified": verified,
            "not_verified": not_verified,
            "no_attempts_logged": null_attempts,
        },
        "attempts_distribution": dict(sorted(attempts_dist.items())),
        "retry_reason_counts_case_level": dict(sorted(reason_counter.items())),
        "baseline_retry_effectiveness": baseline_block,
        "baseline_retry_reason_counts": dict(sorted(baseline_reason_counts.items())),
    }


# ---------------------------------------------------------------------------
# Axis 4 — Stage latency composition
# ---------------------------------------------------------------------------

_STAGES = (
    "query_analysis_ms",
    "context_resolution_ms",
    "retrieve_ms",
    "verify_ms",
    "answer_generation_ms",
)


def axis4_stage_latency(cases: list[dict], baseline: dict | None) -> dict[str, Any]:
    per_stage_raw: dict[str, list[float]] = {s: [] for s in _STAGES}
    e2e_raw: list[float] = []
    for c in cases:
        sl = c.get("stage_latency") or {}
        for s in _STAGES:
            v = sl.get(s)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                per_stage_raw[s].append(float(v))
        e2e_v = c.get("latency_ms")
        if isinstance(e2e_v, (int, float)) and not isinstance(e2e_v, bool):
            e2e_raw.append(float(e2e_v))

    e2e_mean = (sum(e2e_raw) / len(e2e_raw)) if e2e_raw else None
    per_stage: dict[str, dict[str, Any]] = {}
    for s in _STAGES:
        dist = _distribution(per_stage_raw[s])
        share = None
        if dist["mean"] is not None and e2e_mean and e2e_mean > 0:
            share = dist["mean"] / e2e_mean
        per_stage[s] = {**dist, "share_of_e2e": share}

    # cold vs warm split
    cold_raw: dict[str, list[float]] = {s: [] for s in _STAGES}
    warm_raw: dict[str, list[float]] = {s: [] for s in _STAGES}
    cold_e2e: list[float] = []
    warm_e2e: list[float] = []
    for c in cases:
        is_cold = bool(c.get("cold_start"))
        sl = c.get("stage_latency") or {}
        bucket = cold_raw if is_cold else warm_raw
        for s in _STAGES:
            v = sl.get(s)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                bucket[s].append(float(v))
        e2e_v = c.get("latency_ms")
        if isinstance(e2e_v, (int, float)) and not isinstance(e2e_v, bool):
            (cold_e2e if is_cold else warm_e2e).append(float(e2e_v))

    cold_warm = {
        "cold": {
            "n": len(cold_e2e),
            "e2e": _distribution(cold_e2e),
            "per_stage": {s: _distribution(cold_raw[s]) for s in _STAGES},
        },
        "warm": {
            "n": len(warm_e2e),
            "e2e": _distribution(warm_e2e),
            "per_stage": {s: _distribution(warm_raw[s]) for s in _STAGES},
        },
    }

    baseline_stage = (baseline or {}).get("stage_latency") or {}
    baseline_e2e = (baseline or {}).get("latency") or {}
    return {
        "e2e_latency_ms": {
            **_distribution(e2e_raw),
        },
        "per_stage": per_stage,
        "cold_vs_warm": cold_warm,
        "baseline_stage_latency": baseline_stage,
        "baseline_e2e_latency": baseline_e2e,
    }


# ---------------------------------------------------------------------------
# Axis 5 — Answer synthesis
# ---------------------------------------------------------------------------

def axis5_answer_synthesis(cases: list[dict], baseline: dict | None) -> dict[str, Any]:
    confs = _floats([c.get("confidence") for c in cases])
    conf_dist = _distribution(confs)
    # bucket histogram
    conf_hist: dict[str, int] = {}
    for lo, hi in zip(CONFIDENCE_BINS[:-1], CONFIDENCE_BINS[1:]):
        key = f"[{lo:.1f},{hi:.1f})"
        conf_hist[key] = sum(1 for v in confs if lo <= v < hi)
    if confs:
        # include the exact 1.0 cases at the top bin
        conf_hist[f"[{CONFIDENCE_BINS[-2]:.1f},{CONFIDENCE_BINS[-1]:.1f})"] += sum(1 for v in confs if v == 1.0)

    abstention_by_qt: dict[str, dict[str, Any]] = {}
    for c in cases:
        qt = c.get("query_type") or "unknown"
        entry = abstention_by_qt.setdefault(qt, {"n": 0, "abstained": 0})
        entry["n"] += 1
        if c.get("abstained"):
            entry["abstained"] += 1
    for qt, entry in abstention_by_qt.items():
        entry["rate"] = _safe_div(entry["abstained"], entry["n"])

    status_dist = Counter()
    for c in cases:
        status = c.get("answer_status") or "unknown"
        status_dist[str(status)] += 1

    format_compliance = _floats([c.get("answer_format_compliance") for c in cases])
    fc_mean = (sum(format_compliance) / len(format_compliance)) if format_compliance else None

    baseline_overall = {
        "abstention": (baseline or {}).get("abstention"),
        "answer_format_compliance": (baseline or {}).get("answer_format_compliance"),
    }

    return {
        "n_cases": len(cases),
        "confidence": {
            **conf_dist,
            "histogram": conf_hist,
        },
        "abstention_by_query_type": dict(sorted(abstention_by_qt.items())),
        "answer_status_distribution": dict(sorted(status_dist.items())),
        "answer_format_compliance_mean": fc_mean,
        "baseline_overall": baseline_overall,
    }


# ---------------------------------------------------------------------------
# Axis 6 — Evidence quality
# ---------------------------------------------------------------------------

def axis6_evidence_quality(cases: list[dict]) -> dict[str, Any]:
    paired = []
    for c in cases:
        r = c.get("chunk_recall_at_10")
        cp = c.get("citation_precision")
        g = c.get("groundedness")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (r, cp, g)):
            paired.append((float(r), float(cp), float(g)))

    n = len(paired)
    joint = Counter()
    for r, cp, _g in paired:
        r_hi = r >= RECALL_HI_THRESHOLD
        c_hi = cp >= CITATION_HI_THRESHOLD
        key = ("recall_hi" if r_hi else "recall_lo", "cite_hi" if c_hi else "cite_lo")
        joint[key] += 1

    joint_pct = {
        f"{a}_{b}": _safe_div(joint[(a, b)], n)
        for a in ("recall_hi", "recall_lo")
        for b in ("cite_hi", "cite_lo")
    }
    pearson_r_cite = pearson([r for r, _, _ in paired], [c for _, c, _ in paired])
    pearson_r_ground = pearson([r for r, _, _ in paired], [g for _, _, g in paired])
    return {
        "n_paired_cases": n,
        "thresholds": {
            "recall_at_10_hi": RECALL_HI_THRESHOLD,
            "citation_precision_hi": CITATION_HI_THRESHOLD,
        },
        "joint_bucket_share": joint_pct,
        "pearson_recall_at_10_vs_citation_precision": pearson_r_cite,
        "pearson_recall_at_10_vs_groundedness": pearson_r_ground,
        "_raw_paired_recall_cite": [[r, c] for r, c, _ in paired],
    }


# ---------------------------------------------------------------------------
# Axis 7 — Cold-start
# ---------------------------------------------------------------------------

def axis7_cold_start(cases: list[dict]) -> dict[str, Any]:
    cold_cases = [c for c in cases if c.get("cold_start")]
    warm_cases = [c for c in cases if not c.get("cold_start")]

    def _cohort(cs: list[dict]) -> dict[str, Any]:
        e2e = _floats([c.get("latency_ms") for c in cs])
        retrieve = _floats([(c.get("stage_latency") or {}).get("retrieve_ms") for c in cs])
        return {
            "n": len(cs),
            "e2e_latency_ms": _distribution(e2e),
            "retrieve_ms": _distribution(retrieve),
        }

    cold = _cohort(cold_cases)
    warm = _cohort(warm_cases)
    delta_retrieve_p50 = None
    if cold["retrieve_ms"]["p50"] is not None and warm["retrieve_ms"]["p50"] is not None:
        delta_retrieve_p50 = cold["retrieve_ms"]["p50"] - warm["retrieve_ms"]["p50"]
    delta_e2e_p50 = None
    if cold["e2e_latency_ms"]["p50"] is not None and warm["e2e_latency_ms"]["p50"] is not None:
        delta_e2e_p50 = cold["e2e_latency_ms"]["p50"] - warm["e2e_latency_ms"]["p50"]
    return {
        "cold": cold,
        "warm": warm,
        "delta_retrieve_ms_p50_cold_minus_warm": delta_retrieve_p50,
        "delta_e2e_ms_p50_cold_minus_warm": delta_e2e_p50,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(stats: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG Pipeline EDA")
    lines.append("")
    lines.append(
        "7-axis profile of pipeline dynamics observed in ``eval_summary.json``."
        " ADR 0005 boundary: case-level data (case.id, query, answer, evidence text,"
        " retrieved/gold chunk IDs, doc IDs) is read for *numeric aggregation only*."
        " Only means, percentiles, counts, ratios, and Pearson scalars are rendered."
    )
    lines.append("")
    sources = stats.get("_sources") or {}
    lines.append(
        f"Sources: ``{sources.get('eval_summary', '?')}``"
        + (f", ``{sources['baseline']}``" if sources.get('baseline') else "")
    )
    lines.append("")

    # --- Axis 1 ---
    a1 = stats["axis1_retrieval_efficiency"]
    lines.append("## Axis 1 — Retrieval efficiency")
    lines.append("")
    lines.append(
        f"- cases: **{a1['n_cases']}** (with gold_chunk_ids: {a1['n_cases_with_gold_chunks']})"
    )
    lines.append("")
    lines.append("| metric | n | p10 | p50 | p90 | mean |")
    lines.append("|---|---|---|---|---|---|")
    for k in (5, 10, 20):
        d = a1["recall"][f"at_{k}"]
        lines.append(
            f"| recall@{k} | {d['n']} | {_fmt_num(d['p10'])} | {_fmt_num(d['p50'])} | "
            f"{_fmt_num(d['p90'])} | {_fmt_num(d['mean'])} |"
        )
    lines.append(
        f"| MRR | {a1['mrr']['n']} | {_fmt_num(a1['mrr']['p10'])} | {_fmt_num(a1['mrr']['p50'])} | "
        f"{_fmt_num(a1['mrr']['p90'])} | {_fmt_num(a1['mrr']['mean'])} |"
    )
    for k in (10, 20):
        d = a1["ndcg"][f"at_{k}"]
        lines.append(
            f"| NDCG@{k} | {d['n']} | {_fmt_num(d['p10'])} | {_fmt_num(d['p50'])} | "
            f"{_fmt_num(d['p90'])} | {_fmt_num(d['mean'])} |"
        )
    lines.append("")
    if a1["selected_top_k_histogram"]:
        lines.append("### Selected top_k histogram")
        lines.append("")
        lines.append("| top_k | n |")
        lines.append("|---|---|")
        for k, v in a1["selected_top_k_histogram"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # --- Axis 2 ---
    a2 = stats["axis2_reranker_contribution"]
    lines.append("## Axis 2 — Reranker contribution")
    lines.append("")
    lines.append("| metric | n_cases | mean_delta | p50_delta | %_improved | %_unchanged | %_regressed |")
    lines.append("|---|---|---|---|---|---|---|")
    for key, label in (("rerank_delta_mrr", "rerank Δ MRR"), ("rerank_delta_ndcg_at_10", "rerank Δ NDCG@10")):
        b = a2[key]
        lines.append(
            f"| {label} | {b['n_cases_with_rerank']} | "
            f"{_fmt_num(b['mean_delta'])} | {_fmt_num(b['p50_delta'])} | "
            f"{_fmt_pct(b['share_improved'])} | {_fmt_pct(b['share_unchanged'])} | "
            f"{_fmt_pct(b['share_regressed'])} |"
        )
    lines.append("")

    # --- Axis 3 ---
    a3 = stats["axis3_verification_retry"]
    lines.append("## Axis 3 — Verification & retry")
    lines.append("")
    lines.append(f"- verify_rate (verified / verified+failed): **{_fmt_pct(a3['verify_rate'])}**")
    vb = a3["verify_breakdown"]
    lines.append(
        f"- breakdown: verified={vb['verified']}, not_verified={vb['not_verified']},"
        f" no_attempts_logged={vb['no_attempts_logged']}"
    )
    lines.append("")
    lines.append("### Attempts distribution")
    lines.append("")
    lines.append("| attempts | n | share |")
    lines.append("|---|---|---|")
    total_a = sum(a3["attempts_distribution"].values()) or 1
    for k, v in a3["attempts_distribution"].items():
        lines.append(f"| {k} | {v} | {_fmt_pct(v / total_a)} |")
    lines.append("")
    if a3["retry_reason_counts_case_level"]:
        lines.append("### Retry trigger reasons (case-level)")
        lines.append("")
        lines.append("| reason | count |")
        lines.append("|---|---|")
        for reason, count in a3["retry_reason_counts_case_level"].items():
            lines.append(f"| `{reason}` | {count} |")
        lines.append("")
    if a3["baseline_retry_effectiveness"]:
        b = a3["baseline_retry_effectiveness"]
        lines.append(
            f"_Baseline retry_effectiveness:_ "
            f"recovery_rate={_fmt_num(b.get('recovery_rate'))}, "
            f"residual_failure={_fmt_num(b.get('residual_failure'))}, "
            f"retry_lift_vs_no_retry={_fmt_num(b.get('retry_lift_vs_no_retry'))}"
        )
        lines.append("")

    # --- Axis 4 ---
    a4 = stats["axis4_stage_latency"]
    lines.append("## Axis 4 — Stage latency composition")
    lines.append("")
    e2e = a4["e2e_latency_ms"]
    lines.append(
        f"- end-to-end latency_ms (n={e2e['n']}): p50={_fmt_num(e2e['p50'])}, "
        f"p95={_fmt_num(e2e['p95'])}, mean={_fmt_num(e2e['mean'])}"
    )
    lines.append("")
    lines.append("| stage | n | p50 | p95 | mean | share_of_e2e |")
    lines.append("|---|---|---|---|---|---|")
    for s in _STAGES:
        d = a4["per_stage"][s]
        lines.append(
            f"| `{s}` | {d['n']} | {_fmt_num(d['p50'])} | {_fmt_num(d['p95'])} | "
            f"{_fmt_num(d['mean'])} | {_fmt_pct(d['share_of_e2e'])} |"
        )
    lines.append("")
    cw = a4["cold_vs_warm"]
    if cw["cold"]["n"] or cw["warm"]["n"]:
        lines.append("### Cold vs warm e2e latency (ms)")
        lines.append("")
        lines.append("| cohort | n | p50 | p95 | mean |")
        lines.append("|---|---|---|---|---|")
        for cohort in ("cold", "warm"):
            d = cw[cohort]["e2e"]
            lines.append(
                f"| {cohort} | {cw[cohort]['n']} | {_fmt_num(d['p50'])} | "
                f"{_fmt_num(d['p95'])} | {_fmt_num(d['mean'])} |"
            )
        lines.append("")

    # --- Axis 5 ---
    a5 = stats["axis5_answer_synthesis"]
    lines.append("## Axis 5 — Answer synthesis & confidence")
    lines.append("")
    conf = a5["confidence"]
    lines.append(
        f"- confidence (n={conf['n']}): p10={_fmt_num(conf['p10'])}, "
        f"p50={_fmt_num(conf['p50'])}, p90={_fmt_num(conf['p90'])}, mean={_fmt_num(conf['mean'])}"
    )
    lines.append("")
    if conf["histogram"]:
        lines.append("### Confidence histogram")
        lines.append("")
        lines.append("| bin | n |")
        lines.append("|---|---|")
        for k, v in conf["histogram"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
    if a5["abstention_by_query_type"]:
        lines.append("### Abstention by query_type")
        lines.append("")
        lines.append("| query_type | n | abstained | rate |")
        lines.append("|---|---|---|---|")
        for qt, row in a5["abstention_by_query_type"].items():
            lines.append(
                f"| {qt} | {row['n']} | {row['abstained']} | {_fmt_pct(row.get('rate'))} |"
            )
        lines.append("")
    if a5["answer_status_distribution"]:
        lines.append("### Answer status distribution")
        lines.append("")
        lines.append("| status | n |")
        lines.append("|---|---|")
        for k, v in a5["answer_status_distribution"].items():
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
    lines.append(
        f"- overall answer_format_compliance mean: {_fmt_num(a5['answer_format_compliance_mean'])}"
    )
    lines.append("")

    # --- Axis 6 ---
    a6 = stats["axis6_evidence_quality"]
    lines.append("## Axis 6 — Evidence quality (recall × citation × groundedness)")
    lines.append("")
    lines.append(
        f"- paired cases: n={a6['n_paired_cases']} "
        f"(recall@10≥{a6['thresholds']['recall_at_10_hi']}, "
        f"citation_precision≥{a6['thresholds']['citation_precision_hi']})"
    )
    lines.append("")
    lines.append("| | cite_hi | cite_lo |")
    lines.append("|---|---|---|")
    jb = a6["joint_bucket_share"]
    lines.append(
        f"| recall_hi | {_fmt_pct(jb['recall_hi_cite_hi'])} | {_fmt_pct(jb['recall_hi_cite_lo'])} |"
    )
    lines.append(
        f"| recall_lo | {_fmt_pct(jb['recall_lo_cite_hi'])} | {_fmt_pct(jb['recall_lo_cite_lo'])} |"
    )
    lines.append("")
    lines.append(
        f"- Pearson(recall@10, citation_precision) = {_fmt_num(a6['pearson_recall_at_10_vs_citation_precision'])}"
    )
    lines.append(
        f"- Pearson(recall@10, groundedness) = {_fmt_num(a6['pearson_recall_at_10_vs_groundedness'])}"
    )
    lines.append("")

    # --- Axis 7 ---
    a7 = stats["axis7_cold_start"]
    lines.append("## Axis 7 — Cold-start vs warm")
    lines.append("")
    lines.append("| cohort | n | e2e_p50 | e2e_p95 | retrieve_p50 |")
    lines.append("|---|---|---|---|---|")
    for cohort in ("cold", "warm"):
        row = a7[cohort]
        lines.append(
            f"| {cohort} | {row['n']} | {_fmt_num(row['e2e_latency_ms']['p50'])} | "
            f"{_fmt_num(row['e2e_latency_ms']['p95'])} | {_fmt_num(row['retrieve_ms']['p50'])} |"
        )
    lines.append("")
    lines.append(
        f"- Δ retrieve_ms p50 (cold − warm) = {_fmt_num(a7['delta_retrieve_ms_p50_cold_minus_warm'])}"
    )
    lines.append(
        f"- Δ e2e_ms p50 (cold − warm) = {_fmt_num(a7['delta_e2e_ms_p50_cold_minus_warm'])}"
    )
    lines.append("")

    # Figures pointer
    figs = stats.get("_figures_written") or []
    if figs:
        stems = sorted({Path(fp).name for fp in figs})
        lines.append("## Figures")
        lines.append("")
        for name in stems:
            lines.append(f"- `{name}`")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def render_figures(stats: dict[str, Any], out_dir: Path, seed: int) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def _save(fig, stem: str) -> None:
        for ext in ("png", "svg"):
            p = out_dir / f"{stem}.{ext}"
            fig.savefig(p, dpi=144)
            try:
                written.append(str(p.relative_to(REPO_ROOT)))
            except ValueError:
                written.append(str(p))
        plt.close(fig)

    a1 = stats["axis1_retrieval_efficiency"]
    a2 = stats["axis2_reranker_contribution"]
    a3 = stats["axis3_verification_retry"]
    a4 = stats["axis4_stage_latency"]
    a5 = stats["axis5_answer_synthesis"]
    a6 = stats["axis6_evidence_quality"]
    a7 = stats["axis7_cold_start"]

    # Figure 1 — recall@k grouped bar
    ks = (5, 10, 20)
    means = [a1["recall"][f"at_{k}"]["mean"] or 0.0 for k in ks]
    p50s = [a1["recall"][f"at_{k}"]["p50"] or 0.0 for k in ks]
    fig, ax = plt.subplots(figsize=(7, 4))
    x = list(range(len(ks)))
    width = 0.35
    ax.bar([xi - width / 2 for xi in x], means, width=width, label="mean", color="tab:blue")
    ax.bar([xi + width / 2 for xi in x], p50s, width=width, label="p50", color="tab:orange")
    ax.set_xticks(x)
    ax.set_xticklabels([f"recall@{k}" for k in ks])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title(f"Retrieval recall@k (n={a1['n_cases']})")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_retrieval_recall")

    # Figure 2 — rerank delta MRR histogram
    deltas = a2.get("_raw_delta_mrr") or []
    fig, ax = plt.subplots(figsize=(7, 4))
    if deltas:
        ax.hist(deltas, bins=15, color="tab:purple", edgecolor="black", alpha=0.85)
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
    ax.set_xlabel("rerank Δ MRR (post − pre)")
    ax.set_ylabel("Case count")
    ax.set_title(
        f"Reranker MRR delta (n={a2['rerank_delta_mrr']['n_cases_with_rerank']}, "
        f"%improved={_fmt_pct(a2['rerank_delta_mrr']['share_improved'])})"
    )
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_rerank_delta")

    # Figure 3 — retry reason horizontal bar
    reasons = a3.get("retry_reason_counts_case_level") or {}
    if not reasons:
        reasons = a3.get("baseline_retry_reason_counts") or {}
    fig, ax = plt.subplots(figsize=(8, 4))
    if reasons:
        items = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)
        labels = [k for k, _ in items]
        counts = [v for _, v in items]
        ax.barh(range(len(labels))[::-1], counts, color="tab:red")
        ax.set_yticks(range(len(labels))[::-1])
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel("Case count")
    else:
        ax.text(0.5, 0.5, "no retry triggers observed", ha="center", va="center", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title("Retry trigger reasons")
    ax.grid(True, axis="x", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_retry_reasons")

    # Figure 4 — stage latency stacked bar (cold vs warm) — share-of-e2e
    fig, ax = plt.subplots(figsize=(8, 4.5))
    cohorts = ("cold", "warm")
    cw = a4["cold_vs_warm"]
    bottom = [0.0] * len(cohorts)
    palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    cohort_e2e_means = []
    for cohort in cohorts:
        e2e_mean = cw[cohort]["e2e"].get("mean") or 0.0
        cohort_e2e_means.append(e2e_mean)
    for i, s in enumerate(_STAGES):
        vals = []
        for cohort in cohorts:
            stage_mean = cw[cohort]["per_stage"][s].get("mean") or 0.0
            vals.append(stage_mean)
        ax.bar(cohorts, vals, bottom=bottom, label=s.replace("_ms", ""), color=palette[i % len(palette)])
        bottom = [bottom[j] + vals[j] for j in range(len(cohorts))]
    ax.set_ylabel("Mean stage latency (ms)")
    ax.set_title("Stage latency composition: cold vs warm")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_stage_latency")

    # Figure 5 — confidence histogram + abstention by query_type (2 panels)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11, 4))
    hist = a5["confidence"]["histogram"] or {}
    if hist:
        labels = list(hist.keys())
        vals = list(hist.values())
        ax_a.bar(range(len(labels)), vals, color="tab:cyan", edgecolor="black", alpha=0.85)
        ax_a.set_xticks(range(len(labels)))
        ax_a.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax_a.set_title(f"Confidence histogram (n={a5['confidence']['n']})")
    ax_a.set_ylabel("Case count")
    ax_a.grid(True, axis="y", linestyle=":", alpha=0.4)

    abst = a5["abstention_by_query_type"]
    if abst:
        qts = list(abst.keys())
        rates = [(abst[qt]["rate"] or 0.0) for qt in qts]
        ax_b.bar(range(len(qts)), rates, color="tab:olive")
        ax_b.set_xticks(range(len(qts)))
        ax_b.set_xticklabels(qts, rotation=20, ha="right", fontsize=9)
        ax_b.set_ylim(0, 1.05)
    ax_b.set_title("Abstention rate by query_type")
    ax_b.set_ylabel("Rate")
    ax_b.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_confidence")

    # Figure 6 — evidence joint scatter (recall@10 vs citation_precision)
    pairs = a6.get("_raw_paired_recall_cite") or []
    fig, ax = plt.subplots(figsize=(6, 5))
    if pairs:
        rng = random.Random(seed)
        xs = [p[0] + (rng.random() - 0.5) * 0.02 for p in pairs]
        ys = [p[1] + (rng.random() - 0.5) * 0.02 for p in pairs]
        ax.scatter(xs, ys, alpha=0.6, color="tab:green", s=22)
    ax.axhline(CITATION_HI_THRESHOLD, color="black", linestyle=":", linewidth=0.8)
    ax.axvline(RECALL_HI_THRESHOLD, color="black", linestyle=":", linewidth=0.8)
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("chunk_recall_at_10")
    ax.set_ylabel("citation_precision")
    ax.set_title(
        f"Evidence joint (n={a6['n_paired_cases']}, "
        f"Pearson={_fmt_num(a6['pearson_recall_at_10_vs_citation_precision'])})"
    )
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_evidence_joint")

    # Figure 7 — cold vs warm e2e boxplot
    fig, ax = plt.subplots(figsize=(6, 4))
    cold_data = a7["cold"]["e2e_latency_ms"]
    warm_data = a7["warm"]["e2e_latency_ms"]
    # Need raw distributions, but axes only store percentiles. Use the
    # p10/p50/p90 quartiles synthesized — bar plot fallback.
    cohorts = []
    labels = []
    if a7["cold"]["n"]:
        cohorts.append([cold_data["p10"] or 0, cold_data["p50"] or 0, cold_data["p90"] or 0])
        labels.append(f"cold (n={a7['cold']['n']})")
    if a7["warm"]["n"]:
        cohorts.append([warm_data["p10"] or 0, warm_data["p50"] or 0, warm_data["p90"] or 0])
        labels.append(f"warm (n={a7['warm']['n']})")
    if cohorts:
        # plot as three grouped bars: p10 / p50 / p90 per cohort
        x = list(range(len(cohorts)))
        width = 0.25
        for i, q in enumerate(("p10", "p50", "p90")):
            vals = [c[i] for c in cohorts]
            ax.bar([xi + (i - 1) * width for xi in x], vals, width=width, label=q)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
    ax.set_ylabel("e2e latency (ms)")
    ax.set_title("Cold vs warm e2e latency percentiles")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(fig, "real100_rag_cold_warm")

    return sorted(written)


# ---------------------------------------------------------------------------
# Aggregate-only JSON serialization (strips internal _raw fields)
# ---------------------------------------------------------------------------

_PRIVATE_KEYS = (
    "_sources",
    "_figures_written",
    "_raw_delta_mrr",
    "_raw_paired_recall_cite",
)


def strip_private(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if k not in _PRIVATE_KEYS}
    if isinstance(obj, list):
        return [strip_private(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-summary", default="reports/eval_summary.json")
    parser.add_argument("--baseline", default="reports/real100/baseline.aggregate.json")
    parser.add_argument("--out-md", default="reports/rag_pipeline.md")
    parser.add_argument("--out-json", default="reports/rag_pipeline.aggregate.json")
    parser.add_argument("--figures-dir", default="reports/figures")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    eval_path = Path(args.eval_summary)
    if not eval_path.exists():
        print(
            f"ERROR: --eval-summary not found at {eval_path!s}. "
            "Run ``make smoke`` (synthetic) or ``make real-eval`` "
            "(requires eval/real_config.local.yaml) first.",
            file=sys.stderr,
        )
        return 1

    random.seed(args.seed)

    eval_summary = load_eval_summary(eval_path)
    cases = eval_summary.get("case_results") or []
    baseline = load_baseline(Path(args.baseline))

    stats: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "axis1_retrieval_efficiency": axis1_retrieval_efficiency(cases),
        "axis2_reranker_contribution": axis2_reranker_contribution(cases),
        "axis3_verification_retry": axis3_verification_retry(cases, baseline),
        "axis4_stage_latency": axis4_stage_latency(cases, baseline),
        "axis5_answer_synthesis": axis5_answer_synthesis(cases, baseline),
        "axis6_evidence_quality": axis6_evidence_quality(cases),
        "axis7_cold_start": axis7_cold_start(cases),
        "_sources": {
            "eval_summary": str(args.eval_summary),
            "baseline": str(args.baseline) if baseline else None,
        },
    }

    figures_written = render_figures(stats, Path(args.figures_dir), args.seed)
    stats["_figures_written"] = figures_written

    md_text = render_markdown(stats)
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md_text, encoding="utf-8")

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    json_obj = strip_private(stats)
    with out_json.open("w", encoding="utf-8") as fh:
        json.dump(json_obj, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    if figures_written:
        print(f"Wrote {len(figures_written)} figure files under {args.figures_dir}")
    else:
        print("matplotlib not available — figures skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
