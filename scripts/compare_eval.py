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
    detect_abstention_outcome_regressions,
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
    ap.add_argument(
        "--paired-ci",
        action="store_true",
        help=(
            "Append a paired-bootstrap 95%% CI block computed from per-case "
            "`case_results` (local runs only; the aggregate baseline carries "
            "no per-case data per ADR 0005). Display-only — the regression "
            "gate is unchanged."
        ),
    )
    ap.add_argument(
        "--paired-ci-seeds",
        default="17,19,23",
        help="Comma-separated bootstrap seeds for seed-averaged paired CI (default 17,19,23).",
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


def _render_paired_ci_block(base, head, *, seeds) -> list[str]:
    """Per-metric paired-bootstrap CI of (head − base) from ``case_results``.

    Reuses the tested estimators in ``scripts/_ablation_common`` (which the
    retrieval-eval ablation runners already share): cases are paired by
    ``id`` (intersection), ``None`` scores are dropped per ADR 0054
    conditional-metric semantics, and the paired delta CI is seed-averaged.
    Display-only: the regression gate above is unchanged, and a committed
    aggregate baseline (no ``case_results``) degrades to an explanatory note
    rather than a crash.
    """
    # Lazy import: keeps the default compare path free of the eval.bootstrap
    # dependency (imported transitively by _ablation_common). Repo root must
    # be importable for `eval.bootstrap`.
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from _ablation_common import (  # noqa: E402
            _drop_paired_nones,
            _fmt_ci,
            _seed_averaged_paired_ci,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return [f"_Paired CI unavailable: {exc}_"]

    base_cases = base.get("case_results") if isinstance(base, dict) else None
    head_cases = head.get("case_results") if isinstance(head, dict) else None
    if not isinstance(base_cases, list) or not isinstance(head_cases, list):
        return [
            "_Paired CI: requires `case_results` in both runs (local "
            "`eval_summary.json`, not the aggregate baseline — ADR 0005)._"
        ]

    base_by_id = {c["id"]: c for c in base_cases if isinstance(c, dict) and "id" in c}
    common_ids = [
        c["id"]
        for c in head_cases
        if isinstance(c, dict) and c.get("id") in base_by_id
    ]
    head_by_id = {c["id"]: c for c in head_cases if isinstance(c, dict) and "id" in c}
    if not common_ids:
        return ["_Paired CI: no shared case ids between the two runs._"]

    lines = [
        "#### Paired bootstrap 95% CI — head − base (per-case, seed-averaged)",
        "",
        f"- paired cases: {len(common_ids)} · seeds: {list(seeds)}",
        "",
        "| metric | Δ (95% CI) |",
        "|---|---|",
    ]
    for path, label, _higher, gated in METRICS:
        if not gated or "." in path:
            continue
        a = [head_by_id[i].get(path) for i in common_ids]  # other = head
        b = [base_by_id[i].get(path) for i in common_ids]  # current = base
        a_clean, b_clean = _drop_paired_nones(a, b)
        if len(a_clean) < 2:
            lines.append(f"| {label} | N/A (n<2) |")
            continue
        ci = _seed_averaged_paired_ci(a_clean, b_clean, list(seeds))
        lines.append(f"| {label} | {_fmt_ci(ci)} |")
    lines.append("")
    lines.append(
        "_Significance = 95% CI excludes 0 (seed-averaged paired bootstrap). "
        "Display-only; the regression gate above is unchanged._"
    )
    return lines


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
        regressions += detect_abstention_outcome_regressions(base, head)
    lines.extend(_render_gate_block(regressions, allow=args.allow_regression))

    if args.paired_ci:
        seeds = [int(s) for s in str(args.paired_ci_seeds).split(",") if s.strip()]
        lines.append("")
        lines.extend(_render_paired_ci_block(base, head, seeds=seeds))

    print("\n".join(lines))

    if regressions and not args.allow_regression:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
