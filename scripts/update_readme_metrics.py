#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval.bootstrap import format_ci_band  # noqa: E402
from _utils import fmt_rate  # noqa: E402

START_MARKER = "<!-- METRICS_TABLE:START -->"
END_MARKER = "<!-- METRICS_TABLE:END -->"
REQUIRED_KEYS = [
    "accuracy",
    "groundedness",
    "citation_precision",
    "claim_citation_alignment",
    "abstention",
    "answer_format_compliance",
    "latency",
    "retry",
]

# Runs whose CI separates from `full` — shown in main ablation table.
# All other runs are detection-blind under n=42 and go into the collapsed block.
_MAIN_ABLATION_RUNS = {"naive_baseline", "full", "no_metadata_first", "no_verifier_retry"}
_MAIN_ABLATION_ORDER = ["naive_baseline", "full", "no_metadata_first", "no_verifier_retry"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update README metric table from reports/eval_summary.json")
    parser.add_argument("--report", default="reports/eval_summary.json")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--check", action="store_true", help="Fail if README is not up-to-date")
    return parser.parse_args()


def load_summary(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED_KEYS:
        data.setdefault(key, None)
    return data


def fmt_rate_ci(value: Any, ci: Any) -> str:
    """Format ``0.906 (0.78–1.00)`` when a CI dict is available."""
    if isinstance(ci, dict) and ci.get("mean") is not None:
        return format_ci_band(ci, digits=3)
    return fmt_rate(value)


def fmt_rate_ci_compact(value: Any, ci: Any) -> str:
    """Format ``0.906±0.11`` (half-width). Keeps the ablation table narrow."""
    if not isinstance(ci, dict) or ci.get("mean") is None:
        return fmt_rate(value)
    mean = ci["mean"]
    lo = ci.get("ci_lo")
    hi = ci.get("ci_hi")
    if lo is None or hi is None:
        return f"{mean:.3f}"
    half = max(hi - mean, mean - lo)
    return f"{mean:.3f}±{half:.2f}"


def ci_for(summary: Dict[str, Any], metric: str) -> Any:
    ci_block = summary.get("ci")
    if isinstance(ci_block, dict):
        return ci_block.get(metric)
    return None


def ci_from_type(summary: Dict[str, Any], query_type: str, metric: str) -> Any:
    by_type = summary.get("by_slice") or summary.get("by_query_type")
    if not isinstance(by_type, dict):
        return None
    block = by_type.get(query_type)
    if block is None and query_type == "comparison":
        block = by_type.get("multi_doc")
    if isinstance(block, dict):
        return ci_for(block, metric)
    return None


def fmt_latency(value: Any) -> str:
    if isinstance(value, dict):
        p50 = value.get("p50")
        p95 = value.get("p95")
        if isinstance(p50, (int, float)) and isinstance(p95, (int, float)):
            return f"p50 {p50:.1f}ms / p95 {p95:.1f}ms"
    return "N/A"


def metric_from_type(summary: Dict[str, Any], query_type: str, metric: str) -> Any:
    by_type = summary.get("by_slice") or summary.get("by_query_type")
    if not isinstance(by_type, dict):
        return None
    block = by_type.get(query_type)
    if block is None and query_type == "comparison":
        block = by_type.get("multi_doc")
    if not isinstance(block, dict):
        return None
    return block.get(metric)


def fmt_flag(value: Any) -> str:
    return "on" if bool(value) else "off"


def fmt_top_k(value: Any) -> str:
    return str(value) if isinstance(value, int) else "auto"


def _find_run(runs: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    return next((r for r in runs if isinstance(r, dict) and r.get("name") == name), None)


def _delta_pp(full_val: Optional[float], base_val: Optional[float]) -> str:
    if full_val is None or base_val is None:
        return "—"
    delta = (full_val - base_val) * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}pp"


def render_main_table(summary: Dict[str, Any], full_run: Optional[Dict[str, Any]] = None) -> str:
    abstention_value = (
        metric_from_type(summary, "abstention", "abstention")
        or summary.get("abstention")
    )
    abstention_ci = (
        ci_from_type(summary, "abstention", "abstention") or ci_for(summary, "abstention")
    )

    if full_run is None:
        # Fallback to single-column when full pipeline data is unavailable (e.g. CI-only naive_baseline run).
        rows = [
            ("Overall", "Answer Accuracy", fmt_rate_ci(summary.get("accuracy"), ci_for(summary, "accuracy"))),
            (
                "Single-doc extraction",
                "Answer Accuracy",
                fmt_rate_ci(
                    metric_from_type(summary, "single_doc", "accuracy"),
                    ci_from_type(summary, "single_doc", "accuracy"),
                ),
            ),
            (
                "Multi-doc comparison",
                "Groundedness Rate",
                fmt_rate_ci(
                    metric_from_type(summary, "comparison", "groundedness"),
                    ci_from_type(summary, "comparison", "groundedness"),
                ),
            ),
            (
                "Follow-up",
                "Answer Accuracy",
                fmt_rate_ci(
                    metric_from_type(summary, "follow_up", "accuracy"),
                    ci_from_type(summary, "follow_up", "accuracy"),
                ),
            ),
            (
                "Evidence",
                "Citation Precision",
                fmt_rate_ci(summary.get("citation_precision"), ci_for(summary, "citation_precision")),
            ),
            (
                "Evidence",
                "Claim Citation Alignment",
                fmt_rate_ci(
                    summary.get("claim_citation_alignment"),
                    ci_for(summary, "claim_citation_alignment"),
                ),
            ),
            (
                "Evidence",
                "Answer Format Compliance",
                fmt_rate_ci(
                    summary.get("answer_format_compliance"),
                    ci_for(summary, "answer_format_compliance"),
                ),
            ),
            (
                "Abstention",
                "Abstention Accuracy",
                fmt_rate_ci(abstention_value, abstention_ci),
            ),
            ("System", "Latency (p50/p95)", fmt_latency(summary.get("latency"))),
            ("System", "Retry Rate", fmt_rate_ci(summary.get("retry"), ci_for(summary, "retry"))),
        ]
        table = ["| Category | Metric | Score (95% CI) |", "|---|---:|---:|"]
        table.extend(f"| {c} | {m} | {s} |" for c, m, s in rows)
        return "\n".join(table)

    # Three-column mode: agentic_full | naive_baseline | Δ
    full_abstention = (
        metric_from_type(full_run, "abstention", "abstention") or full_run.get("abstention")
    )
    full_abstention_ci = (
        ci_from_type(full_run, "abstention", "abstention") or ci_for(full_run, "abstention")
    )
    latency_full = fmt_latency(full_run.get("latency"))
    latency_base = fmt_latency(summary.get("latency"))

    rows_3col = [
        (
            "Overall", "Answer Accuracy",
            fmt_rate_ci(full_run.get("accuracy"), ci_for(full_run, "accuracy")),
            fmt_rate_ci(summary.get("accuracy"), ci_for(summary, "accuracy")),
            _delta_pp(full_run.get("accuracy"), summary.get("accuracy")),
        ),
        (
            "Single-doc extraction", "Answer Accuracy",
            fmt_rate_ci(
                metric_from_type(full_run, "single_doc", "accuracy"),
                ci_from_type(full_run, "single_doc", "accuracy"),
            ),
            fmt_rate_ci(
                metric_from_type(summary, "single_doc", "accuracy"),
                ci_from_type(summary, "single_doc", "accuracy"),
            ),
            _delta_pp(
                metric_from_type(full_run, "single_doc", "accuracy"),
                metric_from_type(summary, "single_doc", "accuracy"),
            ),
        ),
        (
            "Multi-doc comparison", "Groundedness Rate",
            fmt_rate_ci(
                metric_from_type(full_run, "comparison", "groundedness"),
                ci_from_type(full_run, "comparison", "groundedness"),
            ),
            fmt_rate_ci(
                metric_from_type(summary, "comparison", "groundedness"),
                ci_from_type(summary, "comparison", "groundedness"),
            ),
            _delta_pp(
                metric_from_type(full_run, "comparison", "groundedness"),
                metric_from_type(summary, "comparison", "groundedness"),
            ),
        ),
        (
            "Follow-up", "Answer Accuracy",
            fmt_rate_ci(
                metric_from_type(full_run, "follow_up", "accuracy"),
                ci_from_type(full_run, "follow_up", "accuracy"),
            ),
            fmt_rate_ci(
                metric_from_type(summary, "follow_up", "accuracy"),
                ci_from_type(summary, "follow_up", "accuracy"),
            ),
            _delta_pp(
                metric_from_type(full_run, "follow_up", "accuracy"),
                metric_from_type(summary, "follow_up", "accuracy"),
            ),
        ),
        (
            "Evidence", "Citation Precision",
            fmt_rate_ci(full_run.get("citation_precision"), ci_for(full_run, "citation_precision")),
            fmt_rate_ci(summary.get("citation_precision"), ci_for(summary, "citation_precision")),
            _delta_pp(full_run.get("citation_precision"), summary.get("citation_precision")),
        ),
        (
            "Evidence", "Claim Citation Alignment",
            fmt_rate_ci(full_run.get("claim_citation_alignment"), ci_for(full_run, "claim_citation_alignment")),
            fmt_rate_ci(summary.get("claim_citation_alignment"), ci_for(summary, "claim_citation_alignment")),
            _delta_pp(full_run.get("claim_citation_alignment"), summary.get("claim_citation_alignment")),
        ),
        (
            "Evidence", "Answer Format Compliance",
            fmt_rate_ci(full_run.get("answer_format_compliance"), ci_for(full_run, "answer_format_compliance")),
            fmt_rate_ci(summary.get("answer_format_compliance"), ci_for(summary, "answer_format_compliance")),
            _delta_pp(full_run.get("answer_format_compliance"), summary.get("answer_format_compliance")),
        ),
        (
            "Abstention", "Abstention Accuracy",
            fmt_rate_ci(full_abstention, full_abstention_ci),
            fmt_rate_ci(abstention_value, abstention_ci),
            _delta_pp(full_abstention, abstention_value),
        ),
        (
            "System", "Latency (p50/p95)",
            f"{latency_full} (`agentic_full`)",
            f"{latency_base} (`naive_baseline` — CI source of truth)",
            "—",
        ),
        (
            "System", "Retry Rate",
            fmt_rate_ci(full_run.get("retry"), ci_for(full_run, "retry")),
            fmt_rate_ci(summary.get("retry"), ci_for(summary, "retry")),
            "—",
        ),
    ]
    table = [
        "| Category | Metric | agentic_full (95% CI) | naive_baseline (95% CI) | Δ |",
        "|---|---|---:|---:|---:|",
    ]
    table.extend(f"| {c} | {m} | {f} | {b} | {d} |" for c, m, f, b, d in rows_3col)
    return "\n".join(table)


def _fmt_ablation_row(run: Dict[str, Any]) -> str:
    latency = run.get("latency") if isinstance(run.get("latency"), dict) else {}
    p95 = latency.get("p95") if isinstance(latency, dict) else None
    p95_text = f"{p95:.1f}ms" if isinstance(p95, (int, float)) else "N/A"
    return (
        "| {name} | {pipeline} | {top_k} | {metadata_first} | {rerank} | {verifier_retry}"
        " | {accuracy} | {groundedness} | {citation} | {claim_align}"
        " | {format} | {abstention} | {retry} | {p95} |"
    ).format(
        name=run.get("name", "unknown"),
        pipeline=run.get("pipeline", ""),
        top_k=fmt_top_k(run.get("top_k")),
        metadata_first=fmt_flag(run.get("metadata_first")),
        rerank=fmt_flag(run.get("rerank")),
        verifier_retry=fmt_flag(run.get("verifier_retry")),
        accuracy=fmt_rate_ci_compact(run.get("accuracy"), ci_for(run, "accuracy")),
        groundedness=fmt_rate_ci_compact(run.get("groundedness"), ci_for(run, "groundedness")),
        citation=fmt_rate_ci_compact(run.get("citation_precision"), ci_for(run, "citation_precision")),
        claim_align=fmt_rate_ci_compact(
            run.get("claim_citation_alignment"),
            ci_for(run, "claim_citation_alignment"),
        ),
        format=fmt_rate(run.get("answer_format_compliance")),
        abstention=fmt_rate(run.get("abstention")),
        retry=fmt_rate(run.get("retry")),
        p95=p95_text,
    )


_ABLATION_HEADER = [
    "| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry"
    " | Accuracy | Groundedness | Citation | Claim Align | Format | Abstention | Retry | Latency p95 |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]


def render_ablation_table(summary: Dict[str, Any]) -> str:
    ablation = summary.get("ablation")
    runs = ablation.get("runs") if isinstance(ablation, dict) else None
    if not isinstance(runs, list) or not runs:
        return ""

    order = {n: i for i, n in enumerate(_MAIN_ABLATION_ORDER)}
    main_runs = sorted(
        [r for r in runs if isinstance(r, dict) and r.get("name") in _MAIN_ABLATION_RUNS],
        key=lambda r: order.get(r.get("name", ""), 999),
    )
    blind_runs = [r for r in runs if isinstance(r, dict) and r.get("name") not in _MAIN_ABLATION_RUNS]

    table = ["### Ablation comparison", ""]
    table.extend(_ABLATION_HEADER)
    for run in main_runs:
        table.append(_fmt_ablation_row(run))

    if blind_runs:
        table.append("")
        table.append(
            "<details>"
            "<summary>Detection-blind ablations under n=42 — "
            "statistically inseparable from <code>full</code>; to be re-tested at n≥100 (issue #570)</summary>"
        )
        table.append("")
        table.extend(_ABLATION_HEADER)
        for run in blind_runs:
            table.append(_fmt_ablation_row(run))
        table.append("")
        table.append("</details>")

    table.append("")
    table.append(
        "> Values shown as `mean±half-width` for the 95% bootstrap CI (n=cases, 1000 resamples, seed=17). "
        "The non-CI columns (Format, Abstention, Retry) are point estimates; "
        "their CIs appear in the detailed main table above."
    )
    return "\n".join(table)


def render_table(summary: Dict[str, Any]) -> str:
    ablation = summary.get("ablation", {})
    runs = ablation.get("runs", []) if isinstance(ablation, dict) else []
    full_run = _find_run(runs, "full")
    parts = [render_main_table(summary, full_run)]
    ablation_table = render_ablation_table(summary)
    if ablation_table:
        parts.append(ablation_table)
    return "\n\n".join(parts)


def replace_section(readme_text: str, new_table: str) -> str:
    start = readme_text.find(START_MARKER)
    end = readme_text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError("README marker block not found")
    end += len(END_MARKER)
    block = f"{START_MARKER}\n{new_table}\n{END_MARKER}"
    return readme_text[:start] + block + readme_text[end:]


def normalize_outside_markers(text: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        return text
    end += len(END_MARKER)
    return text[:start] + text[end:]


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    readme_path = Path(args.readme)
    if not report_path.exists() or not readme_path.exists():
        print("[ERROR] Report/README not found", file=sys.stderr)
        return 2

    summary = load_summary(report_path)
    original = readme_path.read_text(encoding="utf-8")
    updated = replace_section(original, render_table(summary))

    if normalize_outside_markers(original) != normalize_outside_markers(updated):
        print("[ERROR] Guard failed: changes detected outside metrics marker block", file=sys.stderr)
        return 3

    if args.check:
        if original != updated:
            print("[FAIL] README metrics table is out of date. Run scripts/update_readme_metrics.py")
            return 1
        print("[OK] README metrics table is up-to-date")
        return 0

    readme_path.write_text(updated, encoding="utf-8")
    print(f"[OK] Updated metrics table in {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
