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
    """Read the CURRENT run's logs from ``runs_dir``.

    When ``agent_evals_run.py`` wrote a ``run_manifest.json``, read ONLY the files
    it lists: a later run with a smaller task list or different seeds overwrites the
    manifest, so the now-orphaned logs from the earlier matrix (same ``start_commit``,
    which ``build_report``'s guard cannot catch) are skipped instead of silently
    inflating the aggregate. Without a manifest (legacy / hand-populated dir) fall
    back to globbing every ``*.json`` — excluding the manifest file itself — and rely
    on the cross-commit guard in ``build_report`` as the remaining safety net.
    """

    runner = load_module(
        "agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_for_report"
    )
    manifest = runner.read_run_manifest(runs_dir)
    if manifest is not None:
        names = manifest.get("run_logs") or []
        missing = [name for name in names if not (runs_dir / name).exists()]
        if missing:
            preview = missing[:3]
            raise FileNotFoundError(
                f"run_manifest.json lists {len(missing)} run-log(s) not on disk "
                f"({preview}{'...' if len(missing) > 3 else ''}); the runs dir is "
                "inconsistent — re-run scripts/agent_evals_run.py."
            )
        return [
            json.loads((runs_dir / name).read_text(encoding="utf-8")) for name in names
        ]
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob("*.json"))
        if path.name != runner.RUN_MANIFEST_NAME
    ]


def _is_accepted(run_log: dict[str, Any]) -> bool:
    return run_log.get("gate_results", {}).get("tier") == ACCEPTED_TIER


def _per_task_playbook(logs: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for log in logs:
        grouped.setdefault((log["task_id"], log["playbook"]), []).append(log)
    return grouped


def _metric_value(metric: str, runs: list[dict[str, Any]]) -> float | None:
    """Compute one (task, playbook) metric value from its seed runs.

    Returns ``None`` when the metric is UNDEFINED for this group — specifically the
    per-accepted cost / human-minute metrics when nothing was accepted. Returning
    ``0.0`` there would make a zero-solve playbook look *cheapest* (best), inverting
    the cost metric: a baseline that solves nothing would tie or beat a candidate
    that solves at nonzero cost. An undefined value is dropped from the paired
    sample (see ``_paired_rows``) rather than scored as free.
    """

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
            return None  # undefined: no accepted run to amortize human-minutes over
        return sum(float(r.get("human_minutes", 0.0)) for r in accepted_runs) / n_accepted
    if metric == "cost_per_accepted":
        if n_accepted == 0:
            return None  # undefined: no accepted run to amortize cost over
        return sum(float(r.get("cost", {}).get("usd", 0.0)) for r in accepted_runs) / n_accepted
    raise ValueError(f"unknown metric: {metric}")


def _paired_rows(metric: str, grouped, task_ids: list[str]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for task_id in task_ids:
        base_runs = grouped.get((task_id, BASELINE_PLAYBOOK))
        cand_runs = grouped.get((task_id, CANDIDATE_PLAYBOOK))
        if not base_runs or not cand_runs:
            continue  # a task missing either playbook cannot form a paired row
        v0 = _metric_value(metric, base_runs)
        v1 = _metric_value(metric, cand_runs)
        if v0 is None or v1 is None:
            # Metric undefined for one side (e.g. zero-accepted cost_per_accepted):
            # a paired delta is only meaningful when both sides are defined, so drop
            # this task from THIS metric's sample rather than scoring it as 0.0.
            continue
        rows.append({"v0": v0, "v1": v1})
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

    # Fail loud on a dirty runs directory: the gitignored runs dir is read whole
    # (every *.json), and the run script overwrites only the current matrix's
    # filenames — it never clears older files. If logs from a DIFFERENT start_commit
    # are still present, folding them into one aggregate would silently corrupt
    # task_count / means / deltas (comparing measurements taken at different code
    # states). Refuse rather than corrupt; the operator should report from a fresh
    # --runs-dir per matrix. (Same-commit stale tasks remain valid measurements at
    # that commit and are not blocked here.)
    start_commits = sorted({log["start_commit"] for log in logs if log.get("start_commit")})
    if len(start_commits) > 1:
        raise ValueError(
            "run-logs span multiple start_commit values "
            f"({start_commits}); stale logs would corrupt the aggregate. "
            "Use a fresh --runs-dir for a clean matrix, or remove stale logs."
        )

    grouped = _per_task_playbook(logs)
    task_ids = sorted({task_id for (task_id, _playbook) in grouped})

    metrics_block: dict[str, Any] = {}
    n_by_metric: dict[str, int] = {}
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
        n_by_metric[metric] = delta.n
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

    # Headline N reflects the PRIMARY metric (accepted_solve_rate). The per-accepted
    # cost / human-minute metrics can have a SMALLER n after dropping zero-accepted
    # tasks (P3), so they must not set the headline sample size; each metric row
    # still carries its own ``n``.
    n_for_notes = n_by_metric.get("accepted_solve_rate", 0)
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
