#!/usr/bin/env python3
"""Distinguishing-power gauge for real-data eval ablations (ADR 0053 §Consequences).

Reads an ``eval_summary.json`` (default ``reports/real100/eval_summary.json``)
that contains three ablation runs — ``full``, ``random_retrieval``,
``single_chunk`` (ADR 0053 floors) — and computes per-metric gauges:

* **Raw gap** = ``default − floor`` for each (metric, floor) pair.
* **Normalized score** = ``(default − floor) / (1 − floor)`` — what fraction
  of the remaining headroom above the floor the default occupies. ADR 0053
  §Consequences names this the "is the signal alive" gauge.

Two outputs (both committable per ADR 0005 — aggregate-only, no per-case
data is ever read):

* ``reports/real100/distinguishing_power.md`` — markdown table for human
  inspection / PR-D README ingestion.
* ``reports/real100/distinguishing_power.aggregate.json`` — machine-readable
  schema for downstream tooling (PR-D's README auto-regen).

CLI::

    python3 scripts/distinguishing_power.py
    python3 scripts/distinguishing_power.py --summary path/to/eval_summary.json
    python3 scripts/distinguishing_power.py --out-md path.md --out-json path.json

Exit codes::

    0 — wrote both artifacts successfully
    1 — summary file missing / missing ablation runs / unexpected schema
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Repo root sentinel so the script works whether invoked as
# ``python3 scripts/distinguishing_power.py`` or imported as
# ``scripts.distinguishing_power`` from the test suite.
ROOT = Path(__file__).resolve().parents[1]

# Default I/O paths — all relative to repo root. Overridable via CLI.
DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_MD = ROOT / "reports" / "real100" / "distinguishing_power.md"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100" / "distinguishing_power.aggregate.json"

# Required ablation names. The two floors come from ADR 0053; the default
# label is fixed to ``full`` to match eval/real_config.local.yaml convention
# (ablation_runs[0].name).
DEFAULT_RUN = "full"
FLOOR_RUNS = ("random_retrieval", "single_chunk")
REQUIRED_RUNS = (DEFAULT_RUN, *FLOOR_RUNS)

# Metrics gauged. "abstention" is excluded from the gauge because it is
# a *different objective surface* (correct refusal) — random_retrieval
# legitimately scores high on it (e.g. 0.89 at n=221) without indicating
# the default has lost distinguishing power. The eval_summary will still
# include abstention numbers in its raw run aggregates.
GAUGED_METRICS = (
    "accuracy",
    "groundedness",
    "citation_precision",
    "claim_citation_alignment",
    "answer_format_compliance",
)


def _load_summary(path: Path) -> dict[str, Any]:
    """Load ``eval_summary.json`` and verify the three ablation runs exist.

    Raises ``SystemExit(1)`` with a human-readable error on any structural
    surprise (missing file, missing ``ablation.runs``, missing required run).
    Test-friendly: callers (including the unit test) can catch SystemExit.
    """
    if not path.exists():
        sys.exit(
            f"[ERROR] eval_summary not found: {path}\n"
            f"        Run `make real-eval` first (writes the gitignored summary)."
        )
    with path.open() as fh:
        data = json.load(fh)
    runs = data.get("ablation", {}).get("runs")
    if not isinstance(runs, list):
        sys.exit(
            f"[ERROR] eval_summary {path} has no ablation.runs list — "
            f"distinguishing-power gauge requires the 3-row ablation surface "
            f"(see ADR 0053 + eval/real_config.local.yaml ablation_runs)."
        )
    names = {r.get("name") for r in runs}
    missing = [name for name in REQUIRED_RUNS if name not in names]
    if missing:
        sys.exit(
            f"[ERROR] eval_summary {path} missing required ablation runs: "
            f"{missing}. Expected all of {list(REQUIRED_RUNS)} per ADR 0053. "
            f"Got: {sorted(names)}"
        )
    return data


def _runs_by_name(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index ablation runs by name for O(1) lookup."""
    return {r["name"]: r for r in summary["ablation"]["runs"]}


def _safe_metric(run: dict[str, Any], metric: str) -> float | None:
    """Pull a metric value from an ablation run, tolerating absence.

    Some metrics (e.g. ``citation_precision``) may be ``None`` when n=0
    for the relevant slice. Return ``None`` rather than raising — the
    gauge row for that metric will be marked ``n/a`` in both outputs.
    """
    value = run.get(metric)
    if value is None:
        ci = run.get("ci", {}).get(metric)
        if isinstance(ci, dict):
            value = ci.get("mean")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gauge_row(default: float | None, floor: float | None) -> dict[str, Any]:
    """Compute the raw gap + normalized headroom score for one (metric, floor).

    ``normalized`` is the ADR 0053 §Consequences formula::

        score = (default - floor) / (1 - floor)

    which is the fraction of the remaining headroom-above-floor (ceiling
    of 1.0 assumed since these are all 0..1 rates) that the default occupies.
    A score > 0 means the default beats the floor; ≤ 0 means the default is
    at or below the floor — the "signal is dead" warning state.

    Returns ``{"gap": None, "normalized": None}`` if either input is missing
    or if ``floor == 1`` (degenerate denominator).
    """
    if default is None or floor is None:
        return {"gap": None, "normalized": None}
    gap = default - floor
    denom = 1.0 - floor
    if denom <= 0:
        return {"gap": gap, "normalized": None}
    return {"gap": gap, "normalized": gap / denom}


def compute_gauge(summary: dict[str, Any]) -> dict[str, Any]:
    """Compute the full distinguishing-power gauge from a loaded summary.

    Returns a JSON-serializable dict with this structure::

        {
          "num_predictions": int,
          "runs": {
            "full":             {"accuracy": 0.297, ...},
            "random_retrieval": {"accuracy": 0.025, ...},
            "single_chunk":     {"accuracy": 0.068, ...},
          },
          "gauge": {
            "accuracy": {
              "default":      0.297,
              "vs_random":    {"gap": 0.272, "normalized": 0.279},
              "vs_single":    {"gap": 0.229, "normalized": 0.245},
              "signal_alive": True,  # both gauges > 0
            },
            ...
          }
        }
    """
    runs = _runs_by_name(summary)
    default = runs[DEFAULT_RUN]
    random_run = runs["random_retrieval"]
    single_run = runs["single_chunk"]
    n = default.get("num_predictions") or summary.get("num_predictions")

    out_runs = {
        name: {m: _safe_metric(runs[name], m) for m in GAUGED_METRICS}
        for name in REQUIRED_RUNS
    }
    gauge: dict[str, Any] = {}
    for metric in GAUGED_METRICS:
        d = _safe_metric(default, metric)
        r = _safe_metric(random_run, metric)
        s = _safe_metric(single_run, metric)
        vs_random = _gauge_row(d, r)
        vs_single = _gauge_row(d, s)
        signal_alive = (
            vs_random["gap"] is not None
            and vs_single["gap"] is not None
            and vs_random["gap"] > 0
            and vs_single["gap"] > 0
        )
        gauge[metric] = {
            "default": d,
            "vs_random": vs_random,
            "vs_single": vs_single,
            "signal_alive": signal_alive,
        }
    return {
        "num_predictions": n,
        "runs": out_runs,
        "gauge": gauge,
    }


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _fmt_pp(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.2f}pp"


def render_markdown(gauge: dict[str, Any]) -> str:
    """Render the gauge as a markdown report.

    Layout:
    * Header with ``num_predictions``
    * Raw ablation table (3 columns: full / random / single_chunk)
    * Distinguishing-power gauge table (vs each floor)
    * One-line verdict per metric
    """
    n = gauge["num_predictions"]
    lines: list[str] = [
        "# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)",
        "",
        f"`num_predictions = {n}` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`",
        "",
        "Per ADR 0053 §Consequences:",
        "> PR-5b's `scripts/distinguishing_power.py` can compute "
        "`(default - floor) / (ceiling - floor)` for every leaderboard metric "
        "— a single-number 'is the signal alive' gauge.",
        "",
        "## Ablation raw values",
        "",
        "| metric | full | random_retrieval | single_chunk |",
        "|---|---:|---:|---:|",
    ]
    for metric in GAUGED_METRICS:
        row = [metric]
        for run_name in REQUIRED_RUNS:
            row.append(_fmt_pct(gauge["runs"][run_name][metric]))
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "## Gauge — default vs floors",
        "",
        "| metric | default | gap vs random | normalized vs random | gap vs single_chunk | normalized vs single_chunk | signal alive |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for metric in GAUGED_METRICS:
        g = gauge["gauge"][metric]
        signal_glyph = "yes" if g["signal_alive"] else "no"
        row = [
            metric,
            _fmt_pct(g["default"]),
            _fmt_pp(g["vs_random"]["gap"]),
            _fmt_pct(g["vs_random"]["normalized"]),
            _fmt_pp(g["vs_single"]["gap"]),
            _fmt_pct(g["vs_single"]["normalized"]),
            signal_glyph,
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "## Verdict",
        "",
    ]
    for metric in GAUGED_METRICS:
        g = gauge["gauge"][metric]
        if g["signal_alive"]:
            lines.append(
                f"- **{metric}**: signal alive — default beats both floors "
                f"({_fmt_pp(g['vs_random']['gap'])} vs random, "
                f"{_fmt_pp(g['vs_single']['gap'])} vs single_chunk)."
            )
        elif g["vs_random"]["gap"] is None or g["vs_single"]["gap"] is None:
            lines.append(
                f"- **{metric}**: n/a — one or both floors missing this metric."
            )
        else:
            lines.append(
                f"- **{metric}**: ⚠️ signal NOT alive — default does not beat "
                f"both floors ({_fmt_pp(g['vs_random']['gap'])} vs random, "
                f"{_fmt_pp(g['vs_single']['gap'])} vs single_chunk). "
                f"Retrieval or pipeline not pulling weight on this metric."
            )
    lines.append("")
    lines.append(
        "_Aggregate-only per ADR 0005. No per-case data is read by this script._"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="Path to eval_summary.json (default: %(default)s)",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_OUT_MD,
        help="Path to markdown output (default: %(default)s)",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_OUT_JSON,
        help="Path to JSON aggregate output (default: %(default)s)",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print markdown to stdout, do not write files.",
    )
    args = parser.parse_args(argv)

    summary = _load_summary(args.summary)
    gauge = compute_gauge(summary)
    md = render_markdown(gauge)

    if args.print_only:
        sys.stdout.write(md)
        return 0

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md)
    args.out_json.write_text(json.dumps(gauge, indent=2, sort_keys=True))
    print(f"[OK] Wrote {args.out_md}")
    print(f"[OK] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
