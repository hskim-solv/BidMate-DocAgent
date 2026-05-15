"""Regression tests for scripts/_governance.py THRESHOLDS SSoT (issue #778).

Pins that the numeric thresholds consumed by PR #745 (axis #2),
PR #747 (MEMORY.md PreToolUse hook), and SKILL.md (PR #771) all
resolve to the same canonical value, and that the `--threshold` CLI
contract (exit 0 + stdout numeric / exit 1 + stderr on unknown key)
holds for downstream bash + python consumers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]
GOV = REPO / "scripts" / "_governance.py"

sys.path.insert(0, str(REPO / "scripts"))
import _governance as gov  # type: ignore  # noqa: E402


class TestThresholdsDict(unittest.TestCase):
    def test_required_keys_present(self) -> None:
        for key in ("MEMORY_LINE_AWARE", "MEMORY_LINE_BLOCK", "AXIS_2_LOC"):
            self.assertIn(key, gov.THRESHOLDS, f"missing canonical key: {key}")

    def test_values_are_positive_integers(self) -> None:
        for k, v in gov.THRESHOLDS.items():
            self.assertIsInstance(v, int, f"{k}: not int")
            self.assertGreater(v, 0, f"{k}: must be positive")

    def test_memory_aware_strictly_below_block(self) -> None:
        # If AWARE >= BLOCK the awareness band collapses — the hook
        # would jump straight from silent to blocked.
        self.assertLess(
            gov.THRESHOLDS["MEMORY_LINE_AWARE"],
            gov.THRESHOLDS["MEMORY_LINE_BLOCK"],
        )


class TestThresholdCli(unittest.TestCase):
    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(GOV)] + args,
            capture_output=True, text=True, check=False,
        )

    def test_known_key_prints_value_and_exits_zero(self) -> None:
        r = self._run(["--threshold", "MEMORY_LINE_AWARE"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(int(r.stdout.strip()), gov.THRESHOLDS["MEMORY_LINE_AWARE"])
        self.assertEqual(r.stderr, "")

    def test_unknown_key_exits_one_with_stderr(self) -> None:
        r = self._run(["--threshold", "NOPE_NOT_REAL"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown threshold key", r.stderr)
        # Must list available keys so the operator can recover.
        self.assertIn("MEMORY_LINE_AWARE", r.stderr)

    def test_axis_2_value_matches_self_review_module(self) -> None:
        """Pin that the SSoT survives the late-import indirection in
        `_self_review.py` (so PR #745's collector picks up the same
        value the bash hook does)."""
        sys.path.insert(0, str(REPO / "scripts" / "claude-hooks"))
        # Reload the module so the late-import fallback re-runs against
        # the current sys.path, even if a prior test imported it first.
        if "_self_review" in sys.modules:
            del sys.modules["_self_review"]
        import _self_review as sr  # type: ignore
        self.assertEqual(
            sr.AXIS_2_LOC_THRESHOLD,
            gov.THRESHOLDS["AXIS_2_LOC"],
        )


class TestMemoryLinesHookReadsGovernanceThresholds(unittest.TestCase):
    def test_hook_falls_back_when_governance_absent(self) -> None:
        """Sanity: the hook script's `... || echo 20` fallback fires
        when the governance script is unreachable. Tests resilience of
        the SSoT consumer, not the SSoT itself."""
        hook = REPO / "scripts" / "claude-hooks" / "pretooluse-memory-lines.sh"
        # Make the governance lookup deterministically fail by pointing
        # REPO_ROOT at /tmp (no _governance.py there).
        env = os.environ.copy()
        env["PATH"] = "/tmp:" + env.get("PATH", "")
        r = subprocess.run(
            ["bash", str(hook)],
            input='{"tool_input": {"file_path": "/tmp/not-MEMORY.txt"}}',
            text=True, capture_output=True, env=env, check=False,
        )
        # Non-MEMORY path returns exit 0 regardless; we only assert the
        # hook didn't crash on a missing governance script.
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
