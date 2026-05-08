#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

START_MARKER = "<!-- METRICS_TABLE:START -->"
END_MARKER = "<!-- METRICS_TABLE:END -->"
REQUIRED_KEYS = [
    "accuracy",
    "groundedness",
    "citation_precision",
    "abstention",
    "answer_format_compliance",
    "retrieval",
    "latency",
    "retry",
]


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


def fmt_rate(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


def fmt_latency(value: Any) -> str:
    if isinstance(value, dict):
        p50 = value.get("p50")
        p95 = value.get("p95")
        if isinstance(p50, (int, float)) and isinstance(p95, (int, float)):
            return f"p50 {p50:.1f}ms / p95 {p95:.1f}ms"
    return "N/A"


def metric_from_retrieval(summary: Dict[str, Any], metric: str) -> Any:
    retrieval = summary.get("retrieval")
    if not isinstance(retrieval, dict):
        return None
    return retrieval.get(metric)


def metric_from_type(summary: Dict[str, Any], query_type: str, metric: str) -> Any:
    by_type = summary.get("by_query_type")
    if not isinstance(by_type, dict):
        return None
    block = by_type.get(query_type)
    if not isinstance(block, dict):
        return None
    return block.get(metric)


def fmt_flag(value: Any) -> str:
    return "on" if bool(value) else "off"


def render_main_table(summary: Dict[str, Any]) -> str:
    rows = [
        ("Overall", "Answer Accuracy", fmt_rate(summary.get("accuracy"))),
        (
            "Single-doc extraction",
            "Answer Accuracy",
            fmt_rate(metric_from_type(summary, "single_doc", "accuracy")),
        ),
        (
            "Multi-doc comparison",
            "Groundedness Rate",
            fmt_rate(metric_from_type(summary, "multi_doc", "groundedness")),
        ),
        (
            "Follow-up",
            "Answer Accuracy",
            fmt_rate(metric_from_type(summary, "follow_up", "accuracy")),
        ),
        ("Evidence", "Citation Precision", fmt_rate(summary.get("citation_precision"))),
        ("Evidence", "Answer Format Compliance", fmt_rate(summary.get("answer_format_compliance"))),
        ("Retrieval", "Recall@3", fmt_rate(metric_from_retrieval(summary, "recall_at_3"))),
        ("Retrieval", "MRR", fmt_rate(metric_from_retrieval(summary, "mrr"))),
        (
            "Abstention",
            "Abstention Accuracy",
            fmt_rate(metric_from_type(summary, "abstention", "abstention") or summary.get("abstention")),
        ),
        ("System", "Latency (p50/p95)", fmt_latency(summary.get("latency"))),
        ("System", "Retry Rate", fmt_rate(summary.get("retry"))),
    ]
    table = ["| Category | Metric | Score |", "|---|---:|---:|"]
    table.extend(f"| {c} | {m} | {s} |" for c, m, s in rows)
    return "\n".join(table)


def render_ablation_table(summary: Dict[str, Any]) -> str:
    ablation = summary.get("ablation")
    runs = ablation.get("runs") if isinstance(ablation, dict) else None
    if not isinstance(runs, list) or not runs:
        return ""

    table = [
        "### Ablation comparison",
        "",
        "| Run | Strategy | Metadata-first | Rerank | Verifier/Retry | Retrieval@3 | MRR | Accuracy | Groundedness | Citation | Format | Abstention | Retry | Latency p95 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        if not isinstance(run, dict):
            continue
        latency = run.get("latency") if isinstance(run.get("latency"), dict) else {}
        p95 = latency.get("p95") if isinstance(latency, dict) else None
        p95_text = f"{p95:.1f}ms" if isinstance(p95, (int, float)) else "N/A"
        retrieval = run.get("retrieval") if isinstance(run.get("retrieval"), dict) else {}
        table.append(
            "| {name} | {strategy} | {metadata_first} | {rerank} | {verifier_retry} | {retrieval_at_3} | {mrr} | {accuracy} | {groundedness} | {citation} | {format} | {abstention} | {retry} | {p95} |".format(
                name=run.get("name", "unknown"),
                strategy=run.get("retrieval_strategy") or run.get("retrieval_mode", "flat"),
                metadata_first=fmt_flag(run.get("metadata_first")),
                rerank=fmt_flag(run.get("rerank")),
                verifier_retry=fmt_flag(run.get("verifier_retry")),
                retrieval_at_3=fmt_rate(retrieval.get("recall_at_3")),
                mrr=fmt_rate(retrieval.get("mrr")),
                accuracy=fmt_rate(run.get("accuracy")),
                groundedness=fmt_rate(run.get("groundedness")),
                citation=fmt_rate(run.get("citation_precision")),
                format=fmt_rate(run.get("answer_format_compliance")),
                abstention=fmt_rate(run.get("abstention")),
                retry=fmt_rate(run.get("retry")),
                p95=p95_text,
            )
        )
    return "\n".join(table)


def render_table(summary: Dict[str, Any]) -> str:
    parts = [render_main_table(summary)]
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


def normalize_volatile_latency_values(text: str) -> str:
    normalized_lines = []
    for line in text.splitlines():
        if "| System | Latency (p50/p95) |" in line:
            normalized_lines.append("| System | Latency (p50/p95) | <latency> |")
        elif line.startswith("|") and line.endswith("|") and line.count("|") >= 13:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and cells[0] not in {"Run", "---"}:
                cells[-1] = "<latency>"
                normalized_lines.append("| " + " | ".join(cells) + " |")
            else:
                normalized_lines.append(line)
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


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
            if normalize_volatile_latency_values(original) == normalize_volatile_latency_values(updated):
                print("[OK] README metrics table matches except volatile latency values")
                return 0
            print("[FAIL] README metrics table is out of date. Run scripts/update_readme_metrics.py")
            return 1
        print("[OK] README metrics table is up-to-date")
        return 0

    readme_path.write_text(updated, encoding="utf-8")
    print(f"[OK] Updated metrics table in {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
