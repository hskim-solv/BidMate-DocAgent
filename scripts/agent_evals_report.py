#!/usr/bin/env python3
"""Aggregate agent-evals run-logs into a paired v0-vs-v1 report.

Lives in ``scripts/`` (ordinary tooling, not under the agent-evals allowlist). It
reads GITIGNORED run-logs, builds per-task paired rows (baseline ``v0_naive`` vs
candidate ``v1_spec_first``) for four core metrics, and writes a committable
aggregate report through ``core.report.write_aggregate_report`` — which re-runs the
content scanner and raises if anything fails, so a successful write is the
correctness check.

Metrics (per task, aggregated across seeds):

* ``accepted_solve_rate`` — fraction of seeds whose verdict tier is ``ACCEPTED``.
* ``difficulty_weighted_rate`` — accepted rate scaled by the task difficulty
  weight (smoke tasks default to weight 1.0).
* ``human_min_per_accepted`` — total human-minutes / accepted count (0.0 when no
  accepted run, never a divide-by-zero).
* ``cost_per_accepted`` — total USD / accepted count (0.0 when no accepted run).

For each metric the point estimate is ``core.metrics.paired_delta``. If the paired
sample is NOT underpowered (n >= n_min) a paired bootstrap CI is attached
(``ci_lo``/``ci_hi``/``num_resamples``/``alpha``); if it IS underpowered the row
carries ``underpowered: true`` and OMITS the band — ADR 0100 forbids implying a
precision the surface lacks.

CI computation reuses ``eval.bootstrap.paired_bootstrap_ci`` (numpy). If the
``eval`` package import fails, this script falls back to a path-load of
``eval/bootstrap.py`` and reports the fallback rather than silently skipping the CI.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

ACCEPTED_TIER = "ACCEPTED"
BASELINE_PLAYBOOK = "v0_naive"
CANDIDATE_PLAYBOOK = "v1_spec_first"
DEFAULT_SEEDS = (17, 18, 19)
CORE_METRICS = (
    "accepted_solve_rate",
    "difficulty_weighted_rate",
    "human_min_per_accepted",
    "cost_per_accepted",
)


def load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_paired_bootstrap_ci() -> tuple[Callable[..., Any], str]:
    """Return ``(paired_bootstrap_ci, provenance)``; path-load fallback if needed.

    The preferred path is the package import ``from eval.bootstrap import ...``;
    REPO_ROOT is put on ``sys.path`` first so the package import resolves even when
    the script is launched with ``sys.path[0]`` pointing at ``scripts/``. If the
    package import still fails (e.g. ``eval`` shadowed or numpy missing inside it),
    fall back to a direct path-load of ``eval/bootstrap.py`` and report the
    fallback explicitly rather than silently skipping the CI computation.
    """

    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    try:
        from eval.bootstrap import paired_bootstrap_ci  # type: ignore

        return paired_bootstrap_ci, "eval.bootstrap"
    except Exception:
        module = load_module("eval/bootstrap.py", "agent_evals_bootstrap_fallback")
        return module.paired_bootstrap_ci, "eval/bootstrap.py (path-load fallback)"


def _read_run_logs(runs_dir: Path) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json")):
        logs.append(json.loads(path.read_text(encoding="utf-8")))
    return logs


def _is_accepted(run_log: dict[str, Any]) -> bool:
    return run_log.get("gate_results", {}).get("tier") == ACCEPTED_TIER


def _per_task_playbook(logs: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for log in logs:
        grouped.setdefault((log["task_id"], log["playbook"]), []).append(log)
    return grouped


def _metric_value(metric: str, runs: list[dict[str, Any]]) -> float:
    """Compute one (task, playbook) metric value from its seed runs (safe denom)."""

    n_runs = len(runs)
    accepted_runs = [r for r in runs if _is_accepted(r)]
    n_accepted = len(accepted_runs)
    if metric == "accepted_solve_rate":
        return (n_accepted / n_runs) if n_runs else 0.0
    if metric == "difficulty_weighted_rate":
        weight = float(runs[0].get("difficulty_weight", 1.0)) if runs else 1.0
        return ((n_accepted / n_runs) * weight) if n_runs else 0.0
    if metric == "human_min_per_accepted":
        if n_accepted == 0:
            return 0.0  # safe denom: never divide by zero accepted
        return sum(float(r.get("human_minutes", 0.0)) for r in accepted_runs) / n_accepted
    if metric == "cost_per_accepted":
        if n_accepted == 0:
            return 0.0  # safe denom: never divide by zero accepted
        return sum(float(r.get("cost", {}).get("usd", 0.0)) for r in accepted_runs) / n_accepted
    raise ValueError(f"unknown metric: {metric}")


def _paired_rows(metric: str, grouped, task_ids: list[str]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for task_id in task_ids:
        base_runs = grouped.get((task_id, BASELINE_PLAYBOOK))
        cand_runs = grouped.get((task_id, CANDIDATE_PLAYBOOK))
        if not base_runs or not cand_runs:
            continue  # a task missing either playbook cannot form a paired row
        rows.append(
            {
                "v0": _metric_value(metric, base_runs),
                "v1": _metric_value(metric, cand_runs),
            }
        )
    return rows


def build_report(
    logs: list[dict[str, Any]],
    *,
    report_id: str,
    num_resamples: int,
    alpha: float,
    seed: int,
) -> dict[str, Any]:
    metrics_mod = load_module("agent-evals/core/metrics.py", "agent_evals_metrics_report")
    paired_bootstrap_ci, ci_provenance = _load_paired_bootstrap_ci()

    grouped = _per_task_playbook(logs)
    task_ids = sorted({task_id for (task_id, _playbook) in grouped})

    metrics_block: dict[str, Any] = {}
    n_for_notes = 0
    for metric in CORE_METRICS:
        rows = _paired_rows(metric, grouped, task_ids)
        if not rows:
            continue
        delta = metrics_mod.paired_delta(
            rows,
            baseline_key="v0",
            candidate_key="v1",
            metric=metric,
            baseline_name=BASELINE_PLAYBOOK,
            candidate_name=CANDIDATE_PLAYBOOK,
        )
        row_mapping = delta.to_mapping()
        n_for_notes = delta.n
        if metrics_mod.underpowered(delta.n):
            row_mapping["underpowered"] = True
        else:
            # Arg order is (candidate, baseline) so the CI band is on
            # candidate - baseline, matching paired_delta's delta sign
            # (candidate_mean - baseline_mean). eval.bootstrap.paired_bootstrap_ci
            # computes mean(a) - mean(b), so a=v1 (candidate), b=v0 (baseline).
            ci = paired_bootstrap_ci(
                [r["v1"] for r in rows],
                [r["v0"] for r in rows],
                num_resamples=num_resamples,
                alpha=alpha,
                seed=seed,
            )
            if ci is not None:
                row_mapping["ci_lo"] = round(float(ci["ci_lo"]), 6)
                row_mapping["ci_hi"] = round(float(ci["ci_hi"]), 6)
                row_mapping["num_resamples"] = int(ci["num_resamples"])
                row_mapping["alpha"] = float(ci["alpha"])
            else:
                row_mapping["underpowered"] = True
        metrics_block[metric] = row_mapping

    notes = [
        f"UNDERPOWERED N={n_for_notes}" if metrics_mod.underpowered(n_for_notes) else f"N={n_for_notes}",
        "stub candidate + stub reviewer; no external egress",
        "directional paired signal, not absolute leaderboard",
        "aggregate counts only",
        f"seeds: {', '.join(str(s) for s in DEFAULT_SEEDS)}",
        f"n_min={metrics_mod.N_MIN_DEFAULT}",
        f"ci source: {ci_provenance}",
    ]

    return {
        "schema_version": 1,
        "surface": "agent-evals-pr3",
        "report_id": report_id,
        "generated_by": "scripts/agent_evals_report.py",
        "task_count": len(task_ids),
        "playbooks": {"baseline": BASELINE_PLAYBOOK, "candidate": CANDIDATE_PLAYBOOK},
        "metrics": metrics_block,
        "scanner": {"content_scan": "pass", "path_allowlist": "PR3"},
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default=str(REPO_ROOT / "agent-evals" / "runs"),
        help="GITIGNORED run-log dir (default: agent-evals/runs)",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "agent-evals" / "reports" / "holdout-v0-vs-v1.aggregate.json"),
        help="committable aggregate report path",
    )
    parser.add_argument("--report-id", default="holdout-v0-vs-v1")
    parser.add_argument("--num-resamples", type=int, default=1000)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)

    report_mod = load_module("agent-evals/core/report.py", "agent_evals_report_writer")
    logs = _read_run_logs(Path(args.runs_dir))
    if not logs:
        parser.error(f"no run-logs found under {args.runs_dir} — run scripts/agent_evals_run.py first")

    report = build_report(
        logs,
        report_id=args.report_id,
        num_resamples=args.num_resamples,
        alpha=args.alpha,
        seed=args.seed,
    )
    out_path = Path(args.out)
    rel_path = out_path.resolve().relative_to(REPO_ROOT).as_posix()
    # write_aggregate_report uses its path argument for BOTH scanner validation
    # (as a repo-relative string) and the on-disk write (relative to CWD). Pass the
    # repo-relative path and run the write from REPO_ROOT so it is correct
    # regardless of the process's invocation directory.
    prev_cwd = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        report_mod.write_aggregate_report(Path(rel_path), report)
    finally:
        os.chdir(prev_cwd)
    print(f"wrote aggregate report to {rel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
