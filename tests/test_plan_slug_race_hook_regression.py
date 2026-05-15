"""Regression: PreToolUse plan-slug race hook (issue #779).

Pins the exit-code contract (0 allow / 2 block) for the six matrix
scenarios identified in the issue:

  1. tool_name != Write                       → 0
  2. file_path outside ~/.claude/plans        → 0
  3. plan file does not yet exist             → 0
  4. plan exists + recent + foreign worktree
     marker + cwd inside a different worktree → 2 (block)
  5. plan exists + recent + same worktree
     marker                                   → 0
  6. plan exists + stale mtime (> threshold)  → 0

Each scenario isolates the plans dir into a per-test temp directory by
overriding ``HOME`` (the hook resolves the plans dir from ``$HOME``).
The cwd is set so the hook's worktree detection can be deterministic.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / "scripts" / "claude-hooks" / "plan-slug-race.sh"


class _BaseHookCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="plan-slug-race-")
        self._home = Path(self._tmp) / "home"
        self._plans = self._home / ".claude" / "plans"
        self._plans.mkdir(parents=True)
        # Simulate a worktree-style cwd so the hook's regex parses it.
        self._wt_root = Path(self._tmp) / "project" / ".claude" / "worktrees" / "alpha-1"
        self._wt_root.mkdir(parents=True)
        # The "other" worktree for cross-worktree race scenarios.
        self._wt_other = Path(self._tmp) / "project" / ".claude" / "worktrees" / "beta-2"
        self._wt_other.mkdir(parents=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, payload: dict, *, cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["HOME"] = str(self._home)
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            cwd=str(cwd or self._wt_root),
            check=False,
        )


class TestPlanSlugRaceHook(_BaseHookCase):
    def test_non_write_tool_is_allowed(self) -> None:
        result = self._run({"tool_name": "Edit", "tool_input": {"file_path": "x"}})
        self.assertEqual(0, result.returncode, result.stderr)

    def test_write_outside_plans_dir_is_allowed(self) -> None:
        target = Path(self._tmp) / "outside.md"
        result = self._run({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
        self.assertEqual(0, result.returncode, result.stderr)

    def test_plan_file_missing_is_allowed(self) -> None:
        target = self._plans / "no-such-plan.md"
        result = self._run({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
        self.assertEqual(0, result.returncode, result.stderr)

    def test_recent_foreign_worktree_marker_is_blocked(self) -> None:
        target = self._plans / "racy.md"
        target.write_text(
            "본 plan은 worktree `beta-2` 의 deliverable.\n\n내용 일부.\n",
            encoding="utf-8",
        )
        # mtime is current (~now), so within the default 300s window.
        # cwd is wt_root (slug "alpha-1") — different worktree from
        # the marker ("beta-2"); we expect a block.
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            cwd=self._wt_root,
        )
        self.assertEqual(2, result.returncode, f"stderr={result.stderr}")
        self.assertIn("plan-slug race", result.stderr)
        self.assertIn("beta-2", result.stderr)
        self.assertIn("alpha-1", result.stderr)

    def test_recent_same_worktree_marker_is_allowed(self) -> None:
        target = self._plans / "same.md"
        target.write_text(
            "본 plan은 worktree `alpha-1` 의 deliverable.\n",
            encoding="utf-8",
        )
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            cwd=self._wt_root,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_stale_mtime_is_allowed(self) -> None:
        target = self._plans / "stale.md"
        target.write_text(
            "본 plan은 worktree `beta-2` 의 deliverable.\n",
            encoding="utf-8",
        )
        # Push mtime well past the default 300s window.
        old = time.time() - 10_000
        os.utime(target, (old, old))
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            cwd=self._wt_root,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_no_marker_is_allowed_even_when_recent(self) -> None:
        # Older plans (pre-convention) have no marker → we can't prove a
        # cross-worktree race; stay quiet to keep false-positives low.
        target = self._plans / "no-marker.md"
        target.write_text(
            "# Some plan without a worktree declaration.\n\nbody.\n",
            encoding="utf-8",
        )
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            cwd=self._wt_root,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_caller_outside_worktree_pattern_is_allowed(self) -> None:
        # Main checkout (cwd has no `/.claude/worktrees/<slug>/` segment).
        target = self._plans / "racy2.md"
        target.write_text(
            "본 plan은 worktree `beta-2` 의 deliverable.\n",
            encoding="utf-8",
        )
        main_cwd = Path(self._tmp) / "project"
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            cwd=main_cwd,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_override_via_threshold_zero(self) -> None:
        # PLAN_SLUG_RACE_THRESHOLD=0 makes (age >= threshold) always true → allow.
        target = self._plans / "override.md"
        target.write_text(
            "본 plan은 worktree `beta-2` 의 deliverable.\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["HOME"] = str(self._home)
        env["PLAN_SLUG_RACE_THRESHOLD"] = "0"
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}}),
            text=True,
            capture_output=True,
            env=env,
            cwd=str(self._wt_root),
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
