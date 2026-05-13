#!/usr/bin/env python3
"""Absolute latency SLO check (Tier 2.3 of the senior-signal sprint).

The regression gate in ``scripts/compare_eval.py`` deliberately
excludes latency because CI runner host variance makes relative
comparison flaky. This script applies an *absolute* p95 ceiling per
ablation run as declared in ``eval/config.yaml::latency_budgets`` —
which is the right framing for an operational SLO ("our public synthetic
surface returns within X ms p95") and is robust to runner noise as
long as the ceiling is set with headroom.

Exit codes:
  0 — every ablation that has a budget defined is within ceiling.
  1 — one or more ablations exceeded their budget.
  2 — config or report could not be loaded / parsed.

Ablations without a budget entry are reported but never fail the gate.
Budgets without a matching ablation are reported as orphaned but never
fail the gate (a typo in the budget key shouldn't ship a green SLO).

Usage:
  python scripts/check_latency_slo.py \
      --config eval/config.yaml \
      --summary reports/eval_summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - declared in requirements
    print("ERROR: pyyaml is required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: could not load config {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not load report {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _runs_by_name(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs = (summary.get("ablation") or {}).get("runs") or []
    return {str(r.get("name") or ""): r for r in runs if r.get("name")}


def check(
    config: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (violations, passes, orphans).

    * violations: budget defined AND ablation present AND p95 > ceiling
    * passes: budget defined AND ablation present AND within ceiling
    * orphans: budget keys with no matching ablation run

    Ablations without a budget are not reported either way — quiet by
    design so adding ablations does not force a budget for every one.
    """
    budgets = (config or {}).get("latency_budgets") or {}
    runs = _runs_by_name(summary)
    violations: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    orphans: list[str] = []
    for name, budget in budgets.items():
        run = runs.get(name)
        if run is None:
            orphans.append(name)
            continue
        latency = run.get("latency") or {}
        observed = latency.get("p95")
        ceiling = (budget or {}).get("p95_ms")
        if not isinstance(observed, (int, float)) or not isinstance(ceiling, (int, float)):
            continue
        row = {
            "name": name,
            "observed_p95_ms": float(observed),
            "ceiling_p95_ms": float(ceiling),
            "headroom_ms": round(float(ceiling) - float(observed), 3),
        }
        if observed > ceiling:
            violations.append(row)
        else:
            passes.append(row)
    return violations, passes, orphans


def check_stage(
    config: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (violations, passes, orphans) for per-stage latency SLO.

    ``stage_latency_budgets`` layout in eval/config.yaml::

        stage_latency_budgets:
          <run_name>:
            <stage_name>:
              p95_ms: <ceiling>

    A run without a stage budget entry is silently skipped. A run name
    in the budget with no matching ablation run is reported as orphaned.
    Stage keys without a matching stage_latency entry are silently
    skipped (some stages are absent on simple pipelines).
    """
    stage_budgets = (config or {}).get("stage_latency_budgets") or {}
    runs = _runs_by_name(summary)
    violations: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    orphans: list[str] = []

    for run_name, stage_ceilings in stage_budgets.items():
        run = runs.get(run_name)
        if run is None:
            orphans.append(run_name)
            continue
        stage_latency = run.get("stage_latency") or {}
        for stage_name, ceiling_config in (stage_ceilings or {}).items():
            observed = (stage_latency.get(stage_name) or {}).get("p95")
            ceiling = (ceiling_config or {}).get("p95_ms")
            if not isinstance(observed, (int, float)) or not isinstance(ceiling, (int, float)):
                continue
            row: dict[str, Any] = {
                "name": f"{run_name}/{stage_name}",
                "run": run_name,
                "stage": stage_name,
                "observed_p95_ms": float(observed),
                "ceiling_p95_ms": float(ceiling),
                "headroom_ms": round(float(ceiling) - float(observed), 3),
            }
            if observed > ceiling:
                violations.append(row)
            else:
                passes.append(row)
    return violations, passes, orphans


def _render(violations: list[dict], passes: list[dict], orphans: list[str]) -> str:
    lines: list[str] = []
    if passes:
        lines.append("Within budget:")
        for row in passes:
            lines.append(
                f"  ✅ {row['name']:25s} p95 = {row['observed_p95_ms']:.2f} ms "
                f"≤ ceiling {row['ceiling_p95_ms']:.0f} ms "
                f"(headroom {row['headroom_ms']:.2f} ms)"
            )
    if violations:
        lines.append("")
        lines.append("Budget exceeded:")
        for row in violations:
            lines.append(
                f"  ❌ {row['name']:25s} p95 = {row['observed_p95_ms']:.2f} ms "
                f"> ceiling {row['ceiling_p95_ms']:.0f} ms "
                f"(over by {-row['headroom_ms']:.2f} ms)"
            )
    if orphans:
        lines.append("")
        lines.append("Budget keys with no matching ablation run (likely typo):")
        for name in orphans:
            lines.append(f"  ⚠️  {name}")
    if not (passes or violations or orphans):
        lines.append("No latency budgets defined; nothing to check.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="eval/config.yaml")
    ap.add_argument("--summary", default="reports/eval_summary.json")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    config = _load_yaml(Path(args.config))
    summary = _load_json(Path(args.summary))

    violations, passes, orphans = check(config, summary)
    print(_render(violations, passes, orphans))

    stage_violations, stage_passes, stage_orphans = check_stage(config, summary)
    if stage_violations or stage_passes or stage_orphans:
        print("\n--- Stage-level SLO ---")
        print(_render(stage_violations, stage_passes, stage_orphans))

    return 1 if (violations or stage_violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
