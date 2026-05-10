#!/usr/bin/env python3
"""Render a markdown delta table comparing two eval_summary.json files.

Used by the PR eval workflow to post a base-vs-head comparison comment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# (dotted_path, label, higher_is_better)
METRICS: list[tuple[str, str, bool]] = [
    ("accuracy", "accuracy", True),
    ("groundedness", "groundedness", True),
    ("citation_precision", "citation_precision", True),
    ("citation_grounding", "citation_grounding", True),
    ("claim_citation_alignment", "claim_citation_alignment", True),
    ("answer_format_compliance", "answer_format_compliance", True),
    ("abstention", "abstention (unanswerable cases)", True),
    ("retry", "retry_rate", False),
    ("latency.p50", "latency_p50_ms", False),
    ("latency.p95", "latency_p95_ms", False),
]


def get_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def fmt_delta(base: Any, head: Any, higher_is_better: bool) -> str:
    if not isinstance(base, (int, float)) or not isinstance(head, (int, float)):
        return "—"
    delta = float(head) - float(base)
    if abs(delta) < 5e-4:
        return "·"
    sign = "+" if delta > 0 else ""
    improved = (delta > 0) if higher_is_better else (delta < 0)
    flag = " ✅" if improved else " ⚠️"
    return f"{sign}{delta:.3f}{flag}"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="Base (main) eval_summary.json")
    ap.add_argument("--head", required=True, help="Head (PR) eval_summary.json")
    ap.add_argument("--title", default="Eval delta")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    head = json.loads(Path(args.head).read_text(encoding="utf-8"))

    lines: list[str] = []
    lines.append(f"### {args.title}")
    lines.append("")
    lines.append(
        f"- pipeline: `{head.get('pipeline', '?')}` "
        f"(primary run: `{head.get('primary_run', '?')}`)"
    )
    lines.append(
        f"- cases: base={base.get('num_predictions', '?')} · "
        f"head={head.get('num_predictions', '?')}"
    )
    lines.append("")
    lines.append("| metric | main | PR | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher in METRICS:
        b = get_path(base, path)
        h = get_path(head, path)
        lines.append(f"| {label} | {fmt_value(b)} | {fmt_value(h)} | {fmt_delta(b, h, higher)} |")
    lines.append("")
    lines.append(
        "_✅ direction-of-improvement; ⚠️ direction-of-regression. "
        "Soft check — does not fail CI._"
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
