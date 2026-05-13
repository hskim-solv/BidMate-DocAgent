"""Contract test for the absolute latency SLO gate.

Locks the budget-vs-observed semantics so the CI gate is deterministic
and the orphan-budget warning surfaces typos before they ship a green
SLO ("the budget existed but matched no run").
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_latency_slo import check, check_stage  # noqa: E402


def _summary(runs: list[dict]) -> dict:
    return {"ablation": {"runs": runs}}


class CheckLatencySloUnit(unittest.TestCase):
    def test_passing_run_reported_as_pass(self) -> None:
        config = {"latency_budgets": {"full": {"p95_ms": 100}}}
        summary = _summary([{"name": "full", "latency": {"p95": 5.0}}])
        violations, passes, orphans = check(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]["name"], "full")
        self.assertAlmostEqual(passes[0]["headroom_ms"], 95.0)
        self.assertEqual(orphans, [])

    def test_breach_reported_as_violation(self) -> None:
        config = {"latency_budgets": {"full": {"p95_ms": 100}}}
        summary = _summary([{"name": "full", "latency": {"p95": 250.0}}])
        violations, passes, orphans = check(config, summary)
        self.assertEqual(passes, [])
        self.assertEqual(len(violations), 1)
        self.assertAlmostEqual(violations[0]["headroom_ms"], -150.0)

    def test_ablation_without_budget_is_silent(self) -> None:
        # Adding a new ablation shouldn't force a budget entry — but if
        # the ablation has no matching budget, it must NOT appear in
        # either passes or violations.
        config = {"latency_budgets": {"full": {"p95_ms": 100}}}
        summary = _summary(
            [
                {"name": "full", "latency": {"p95": 5.0}},
                {"name": "unmonitored", "latency": {"p95": 9999.0}},
            ]
        )
        violations, passes, _ = check(config, summary)
        self.assertEqual([p["name"] for p in passes], ["full"])
        self.assertEqual(violations, [])

    def test_orphan_budget_does_not_fail_but_warns(self) -> None:
        # A budget key with no matching ablation = typo in config. We
        # surface it but don't fail the gate (the gate is about runs
        # exceeding their ceiling, not about config hygiene).
        config = {"latency_budgets": {"typo_name": {"p95_ms": 100}}}
        summary = _summary([{"name": "full", "latency": {"p95": 5.0}}])
        violations, passes, orphans = check(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])
        self.assertEqual(orphans, ["typo_name"])

    def test_missing_latency_block_is_skipped(self) -> None:
        # A run with no latency block (rare, but possible during a
        # bootstrap or under errored eval) is silently skipped.
        config = {"latency_budgets": {"full": {"p95_ms": 100}}}
        summary = _summary([{"name": "full"}])
        violations, passes, _ = check(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])

    def test_empty_budgets_is_a_no_op(self) -> None:
        # If config has no latency_budgets, the gate is a no-op (exit 0
        # in CLI; empty results in the unit signature).
        config = {}
        summary = _summary([{"name": "full", "latency": {"p95": 9999.0}}])
        violations, passes, orphans = check(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])
        self.assertEqual(orphans, [])


def _stage_summary(run_name: str, stages: dict) -> dict:
    """Build a minimal eval_summary.json with stage_latency for one run."""
    return {"ablation": {"runs": [{"name": run_name, "stage_latency": stages}]}}


class CheckStageSloUnit(unittest.TestCase):
    """Issue #625 — per-stage SLO gate (check_stage)."""

    def test_passing_stage_reported_as_pass(self) -> None:
        config = {"stage_latency_budgets": {"full": {"query_analysis_ms": {"p95_ms": 50}}}}
        summary = _stage_summary("full", {"query_analysis_ms": {"p95": 2.0}})
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]["stage"], "query_analysis_ms")
        self.assertAlmostEqual(passes[0]["headroom_ms"], 48.0)

    def test_breach_reported_as_violation(self) -> None:
        config = {"stage_latency_budgets": {"full": {"query_analysis_ms": {"p95_ms": 50}}}}
        summary = _stage_summary("full", {"query_analysis_ms": {"p95": 75.0}})
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(passes, [])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["stage"], "query_analysis_ms")
        self.assertAlmostEqual(violations[0]["headroom_ms"], -25.0)

    def test_run_without_stage_budget_is_silent(self) -> None:
        config = {"stage_latency_budgets": {"full": {"query_analysis_ms": {"p95_ms": 50}}}}
        summary = _stage_summary("naive_baseline", {"query_analysis_ms": {"p95": 9999.0}})
        # naive_baseline has no budget → silently skipped
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])

    def test_missing_stage_in_run_skipped_silently(self) -> None:
        # naive pipeline may have no verify_ms — don't fail on absence
        config = {"stage_latency_budgets": {"naive_baseline": {"verify_ms": {"p95_ms": 20}}}}
        summary = _stage_summary("naive_baseline", {})
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])

    def test_orphan_run_name_reported(self) -> None:
        config = {"stage_latency_budgets": {"typo_run": {"query_analysis_ms": {"p95_ms": 50}}}}
        summary = _stage_summary("full", {"query_analysis_ms": {"p95": 2.0}})
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(orphans, ["typo_run"])

    def test_no_stage_latency_budgets_is_noop(self) -> None:
        config = {}
        summary = _stage_summary("full", {"query_analysis_ms": {"p95": 9999.0}})
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(violations, [])
        self.assertEqual(passes, [])
        self.assertEqual(orphans, [])

    def test_multiple_stages_all_checked(self) -> None:
        config = {
            "stage_latency_budgets": {
                "full": {
                    "query_analysis_ms": {"p95_ms": 50},
                    "retrieve_ms": {"p95_ms": 50},
                    "verify_ms": {"p95_ms": 50},
                }
            }
        }
        summary = _stage_summary(
            "full",
            {
                "query_analysis_ms": {"p95": 2.0},
                "retrieve_ms": {"p95": 100.0},  # breach
                "verify_ms": {"p95": 1.0},
            },
        )
        violations, passes, orphans = check_stage(config, summary)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["stage"], "retrieve_ms")
        self.assertEqual(len(passes), 2)


class CheckLatencySloCli(unittest.TestCase):
    def _run(self, config: dict, summary: dict) -> subprocess.CompletedProcess:
        td = Path(tempfile.mkdtemp())
        import yaml
        (td / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        (td / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_latency_slo.py"),
                "--config", str(td / "config.yaml"),
                "--summary", str(td / "summary.json"),
            ],
            capture_output=True,
            text=True,
        )

    def test_cli_exits_zero_when_within_budget(self) -> None:
        result = self._run(
            {"latency_budgets": {"full": {"p95_ms": 100}}},
            _summary([{"name": "full", "latency": {"p95": 5.0}}]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Within budget", result.stdout)

    def test_cli_exits_one_on_breach(self) -> None:
        result = self._run(
            {"latency_budgets": {"full": {"p95_ms": 100}}},
            _summary([{"name": "full", "latency": {"p95": 250.0}}]),
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Budget exceeded", result.stdout)


if __name__ == "__main__":
    unittest.main()
