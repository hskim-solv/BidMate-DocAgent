"""Regression: `make smoke` depends on `install-hooks` (issue #719).

Pins that the first `make smoke` on a fresh worktree automatically
activates `.githooks/` so `.hook-fires.log` (axis #3 자동화 ROI signal)
starts being written without a separate manual step.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]


class TestSmokeDependsOnInstallHooks(unittest.TestCase):
    def test_make_smoke_dryrun_triggers_install_hooks_recipe(self) -> None:
        r = subprocess.run(
            ["make", "-n", "smoke"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            r.returncode, 0,
            f"`make -n smoke` failed: stdout={r.stdout!r} stderr={r.stderr!r}",
        )
        self.assertIn(
            "git config core.hooksPath .githooks",
            r.stdout,
            "smoke target must depend on install-hooks so a fresh worktree "
            "activates .githooks/ before the first eval run.",
        )


if __name__ == "__main__":
    unittest.main()
