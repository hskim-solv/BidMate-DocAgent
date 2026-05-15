"""Regression tests for `--window-days N` CLI mode (issue #716).

Pins rolling-window hook-fires summary emit: positive-N parsing,
mutex with `--quarter`, missing-mode rejection, and that fires
outside the [today-N, today] window are excluded.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "claude-hooks" / "_self_review.py"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


class TestWindowDaysMode(unittest.TestCase):
    def test_emits_fires_within_7day_window(self):
        today = datetime.now(timezone.utc).date()
        inside = (today - timedelta(days=1)).isoformat()
        outside = (today - timedelta(days=14)).isoformat()
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(
                f"{inside}T10:00:00Z|aware|load-bearing|rag_core.py\n"
                f"{outside}T10:00:00Z|aware|load-bearing|old.py\n"
            )
            result = _run("--window-days", "7", "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["window_days"], 7)
        self.assertEqual(
            data["governance_hooks"]["pretooluse_loadbearing_fires"], 1
        )
        self.assertIn("aware", data["governance_hooks"]["fires_by_action"])

    def test_absent_log_emits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            result = _run("--window-days", "7", "--repo", td)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(
            data["governance_hooks"]["pretooluse_loadbearing_fires"], 0
        )

    def test_quarter_and_window_mutually_exclusive(self):
        result = _run("--quarter", "Q2-2026", "--window-days", "7")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with", result.stderr)

    def test_missing_mode_rejected(self):
        result = _run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one of the arguments", result.stderr)

    def test_non_positive_window_rejected(self):
        for n in ("0", "-3"):
            with self.subTest(n=n):
                result = _run("--window-days", n, "--repo", ".")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("must be positive", result.stderr)


if __name__ == "__main__":
    unittest.main()
