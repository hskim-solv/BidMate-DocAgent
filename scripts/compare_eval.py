#!/usr/bin/env python3
"""Render a markdown delta table comparing two eval_summary.json files.

Used by the PR eval workflow to post a base-vs-head comparison comment.
Metric list and formatting helpers live in scripts/_eval_delta.py so the
harness matrix compare reuses the same surface.

Regression gate:
  Pass ``--regression-threshold <delta>`` (default 0.05) to additionally
  enforce that no *gated* metric (quality metrics — accuracy,
  groundedness, citation_precision, etc.; latency is excluded) regresses
  by more than ``threshold`` absolute points relative to the base run.
  On regression, exit code is 1 and a "FAIL" block is appended to the
  rendered table for the PR comment.

  An intentional regression can be acknowledged in the PR body with
  ``[ALLOW_REGRESSION: <reason>]`` — when ``--allow-regression`` is
  passed (or env ``ALLOW_REGRESSION=true``), the script still annotates
  the regression in the comment but exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eval_delta import (  # noqa: E402
    METRICS,
    detect_regressions,
    fmt_delta,
    fmt_value,
    get_path,
    min_num_predictions,
)

DEFAULT_REGRESSION_THRESHOLD = 0.05
ENV_ALLOW_REGRESSION = "ALLOW_REGRESSION"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="Base (main) eval_summary.json")
    ap.add_argument("--head", required=True, help="Head (PR) eval_summary.json")
    ap.add_argument("--title", default="Eval delta")
    ap.add_argument(
        "--regression-threshold",
        type=float,
        default=DEFAULT_REGRESSION_THRESHOLD,
        help=(
            "Absolute threshold for the gate on quality metrics "
            f"(default {DEFAULT_REGRESSION_THRESHOLD}). 0 disables the gate."
        ),
    )
    ap.add_argument(
        "--allow-regression",
        action="store_true",
        default=_env_flag(ENV_ALLOW_REGRESSION),
        help=(
            "Acknowledge an intentional regression. The comment still "
            f"surfaces the regression; the script exits 0. Env: {ENV_ALLOW_REGRESSION}."
        ),
    )
    return ap.parse_args()


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "y")


def _render_gate_block(regressions: list[dict], *, allow: bool) -> list[str]:
    if not regressions:
        return [
            "_✅ direction-of-improvement; ⚠️ direction-of-regression. "
            "Gated quality metrics passed within threshold._"
        ]
    bullets = []
    for r in regressions:
        bullets.append(
            f"  - **{r['metric']}**: base {r['base']:.3f} → PR {r['head']:.3f} "
            f"(Δ {r['delta']:+.3f}, threshold ±{r['threshold']})"
        )
    if allow:
        header = (
            "**⚠️ Acknowledged regression** — `[ALLOW_REGRESSION]` tag detected. "
            "Reviewers please confirm the trade-off is intentional."
        )
    else:
        header = (
            "**❌ Regression gate failed** — the metrics below dropped beyond "
            "the threshold. Add `[ALLOW_REGRESSION: <reason>]` to the PR body "
            "to acknowledge an intentional trade-off."
        )
    return [header, *bullets]


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
    n_min = min_num_predictions(base, head)
    lines.append("| metric | main | PR | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher, _gated in METRICS:
        b = get_path(base, path)
        h = get_path(head, path)
        lines.append(
            f"| {label} | {fmt_value(b)} | {fmt_value(h)} | "
            f"{fmt_delta(b, h, higher, n_min=n_min)} |"
        )
    lines.append("")

    regressions: list[dict] = []
    if args.regression_threshold > 0:
        regressions = detect_regressions(base, head, threshold=args.regression_threshold)
    lines.extend(_render_gate_block(regressions, allow=args.allow_regression))

    print("\n".join(lines))

    if regressions and not args.allow_regression:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
