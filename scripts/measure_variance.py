"""N-run variance measurement for real-eval `eval_summary.json` snapshots.

Issue J — variance source 진단 audit (ADR 0059 supply 3 prerequisite).

Reads N eval_summary.json files produced at the same git HEAD + same config,
and emits:

1. per-category run mean / std / min / max for the 7 ADR 0059 categories.
2. ADR 0059 first-match contract check per run
   (`failure_category_counts.verifier_false_negative ==
   abstention_outcomes.incorrect_answer`).
3. Per-case "stable / fluctuating" classification — how many distinct
   categories did each case see across the N runs?
4. Transition matrix — for cases that fluctuated, which (from, to) pairs
   are dominant?

Strict-forbid: this script does NOT run any eval. It is a read-only
consumer of N eval_summary.json files that the user has already produced
(e.g. via a `for i in 1..5; do make real-eval; cp ...; done` loop).

ADR 0005 boundary: outputs are aggregate-only (no per-case query / answer
text crosses the boundary). Only case_id + 7-category counts.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FAILURE_CATEGORIES = (
    "retrieval_miss",
    "planner_under_decomposition",
    "verifier_false_negative",
    "verifier_false_positive",
    "generator_hallucination",
    "context_dilution",
    "unknown",
)


def _load_runs(glob_pattern: str) -> list[tuple[str, dict[str, Any]]]:
    """Load N eval_summary.json files matching the glob pattern."""
    paths = sorted(glob.glob(glob_pattern))
    if not paths:
        raise SystemExit(f"no files matched: {glob_pattern}")
    runs = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            runs.append((Path(path).name, json.load(fh)))
    return runs


def _category_counts(run: dict[str, Any]) -> dict[str, int]:
    """Extract 7-category counts from a single eval_summary.json (top-level)."""
    fcc = run.get("failure_category_counts") or {}
    return {cat: int(fcc.get(cat, 0)) for cat in FAILURE_CATEGORIES}


def _contract_check(run: dict[str, Any]) -> tuple[int, int, bool]:
    """Return (vfn, incorrect_answer, contract_ok)."""
    vfn = int(run.get("failure_category_counts", {}).get("verifier_false_negative", 0))
    ao = run.get("abstention_outcomes", {}) or {}
    incorrect = int(ao.get("incorrect_answer", 0))
    return vfn, incorrect, vfn == incorrect


def _per_case_categories(run: dict[str, Any]) -> dict[str, str]:
    """Return case_id → failure_category (None → 'success')."""
    out: dict[str, str] = {}
    for cr in run.get("case_results", []) or []:
        cid = cr.get("case_id")
        if cid is None:
            # Fall back to a stable surrogate (query hash if present)
            cid = cr.get("query_hash") or cr.get("query", "")[:64]
        cat = cr.get("failure_category") or "success"
        out[str(cid)] = cat
    return out


def build_aggregate(runs: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Build the aggregate JSON."""
    n = len(runs)
    per_run_counts = [_category_counts(r) for _, r in runs]
    per_run_contracts = [_contract_check(r) for _, r in runs]

    # Per-category stats
    category_stats: dict[str, dict[str, float | int]] = {}
    for cat in FAILURE_CATEGORIES:
        values = [pc[cat] for pc in per_run_counts]
        category_stats[cat] = {
            "values": values,
            "mean": round(statistics.mean(values), 2),
            "stdev": round(statistics.stdev(values), 2) if n > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "spread": max(values) - min(values),
        }

    # Per-case stability
    per_case_by_run = [_per_case_categories(r) for _, r in runs]
    all_case_ids = set()
    for d in per_case_by_run:
        all_case_ids.update(d.keys())

    case_categories: dict[str, list[str]] = {}
    for cid in all_case_ids:
        case_categories[cid] = [d.get(cid, "absent") for d in per_case_by_run]

    distinct_per_case = {cid: len(set(seq)) for cid, seq in case_categories.items()}
    stable_count = sum(1 for n_distinct in distinct_per_case.values() if n_distinct == 1)
    fluctuating_count = sum(1 for n_distinct in distinct_per_case.values() if n_distinct > 1)

    # Transition matrix on fluctuating cases (consecutive pair counts).
    transitions: Counter[tuple[str, str]] = Counter()
    for cid, seq in case_categories.items():
        if distinct_per_case[cid] <= 1:
            continue
        for a, b in zip(seq[:-1], seq[1:]):
            if a != b:
                transitions[(a, b)] += 1

    transition_top = [
        {"from": a, "to": b, "count": c}
        for (a, b), c in transitions.most_common(15)
    ]

    # Per-case breakdown of fluctuating cases (by distinct count).
    fluctuation_histogram = Counter(distinct_per_case.values())

    return {
        "schema_version": 1,
        "n_runs": n,
        "run_files": [name for name, _ in runs],
        "category_stats": category_stats,
        "contract_check": [
            {"run": name, "vfn": vfn, "incorrect_answer": inc, "ok": ok}
            for (name, _), (vfn, inc, ok) in zip(runs, per_run_contracts)
        ],
        "contract_all_ok": all(ok for _, _, ok in per_run_contracts),
        "per_case_stability": {
            "total_cases": len(all_case_ids),
            "stable": stable_count,
            "fluctuating": fluctuating_count,
            "fluctuation_histogram": dict(fluctuation_histogram),
        },
        "transitions_top15": transition_top,
    }


def render_markdown(agg: dict[str, Any]) -> str:
    """Render the aggregate as a human-readable markdown report."""
    lines: list[str] = []
    n = agg["n_runs"]
    lines.append(f"# Variance measurement — N={n} runs at same HEAD\n")
    lines.append("Reads N `eval_summary.json` snapshots produced at the same git HEAD")
    lines.append("+ same `eval/real_config.local.yaml`. Emits per-category mean/std/")
    lines.append("min/max + per-case stability + transition matrix.\n")

    # Per-category stats
    lines.append("## 7-category run statistics\n")
    lines.append("| category | values | mean | stdev | min | max | spread |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    stats = agg["category_stats"]
    # Order by mean desc
    by_mean = sorted(stats.items(), key=lambda kv: -kv[1]["mean"])
    for cat, s in by_mean:
        vals = ", ".join(str(v) for v in s["values"])
        lines.append(
            f"| {cat} | {vals} | {s['mean']} | {s['stdev']} | {s['min']} | {s['max']} | {s['spread']} |"
        )
    lines.append("")

    # Contract check
    lines.append("## ADR 0059 first-match contract per run\n")
    lines.append("`failure_category_counts.verifier_false_negative == abstention_outcomes.incorrect_answer`\n")
    lines.append("| run | vfn | incorrect_answer | contract |")
    lines.append("|---|---:|---:|:---:|")
    for cc in agg["contract_check"]:
        mark = "✓" if cc["ok"] else "✗"
        lines.append(f"| {cc['run']} | {cc['vfn']} | {cc['incorrect_answer']} | {mark} |")
    lines.append(f"\n**All runs contract ok**: {'✓' if agg['contract_all_ok'] else '✗'}\n")

    # Per-case stability
    stab = agg["per_case_stability"]
    lines.append("## Per-case stability\n")
    lines.append(f"- Total cases observed: {stab['total_cases']}")
    lines.append(f"- Stable (same category across all runs): {stab['stable']}")
    lines.append(f"- Fluctuating (≥2 distinct categories): {stab['fluctuating']}\n")
    lines.append("**Fluctuation histogram** (distinct_count → number of cases):\n")
    lines.append("| distinct categories | case count |")
    lines.append("|---:|---:|")
    for n_distinct, cnt in sorted(stab["fluctuation_histogram"].items()):
        lines.append(f"| {n_distinct} | {cnt} |")
    lines.append("")

    # Transitions
    lines.append("## Transition matrix (top 15)\n")
    lines.append("Consecutive (run_i → run_{i+1}) category transitions on fluctuating cases.\n")
    if not agg["transitions_top15"]:
        lines.append("(no transitions — all cases stable)\n")
    else:
        lines.append("| from | to | count |")
        lines.append("|---|---|---:|")
        for t in agg["transitions_top15"]:
            lines.append(f"| {t['from']} | {t['to']} | {t['count']} |")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--eval-summary-glob",
        required=True,
        help="glob pattern matching N eval_summary.json files (e.g. 'reports/real100/variance_runs/run_*.json')",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="aggregate JSON output path",
    )
    parser.add_argument(
        "--output-md",
        required=True,
        type=Path,
        help="markdown report output path",
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=None,
        help="expected number of runs; fails if mismatch (defensive)",
    )
    args = parser.parse_args(argv)

    runs = _load_runs(args.eval_summary_glob)
    if args.n_runs is not None and len(runs) != args.n_runs:
        print(
            f"ERROR: --n-runs={args.n_runs} but glob matched {len(runs)} files",
            file=sys.stderr,
        )
        return 1

    agg = build_aggregate(runs)
    md = render_markdown(agg)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")
    args.output_md.write_text(md, encoding="utf-8")

    print(f"[OK] aggregate written: {args.output}")
    print(f"[OK] markdown written:  {args.output_md}")
    print(f"  n_runs={len(runs)}")
    print(f"  contract_all_ok={agg['contract_all_ok']}")
    print(f"  fluctuating cases: {agg['per_case_stability']['fluctuating']}/{agg['per_case_stability']['total_cases']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
