#!/usr/bin/env python3
"""Render a markdown delta table comparing two eval_summary.json files.

Used by the PR eval workflow to post a base-vs-head comparison comment.
Metric list and formatting helpers live in scripts/_eval_delta.py so the
harness matrix compare reuses the same surface.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eval_delta import METRICS, fmt_delta, fmt_value, get_path  # noqa: E402


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
