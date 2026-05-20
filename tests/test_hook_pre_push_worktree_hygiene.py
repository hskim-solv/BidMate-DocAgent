"""Regression: pre-push orphan-worktree hygiene (issue #1052).

Pins the soft-warn contract (always exit 0; warning only on stderr) for
`.githooks/_pre-push-worktree-hygiene.sh`:

  1. worktree whose branch is merged into main → exit 0, stderr names it
  2. worktree whose branch is NOT merged       → exit 0, stderr quiet
  3. detached-HEAD worktree                     → exit 0, stderr quiet
  4. run from the orphan worktree itself        → exit 0, not self-flagged

Each scenario runs in an isolated temp git repo with real `git worktree`
checkouts. The hook is pure git (no python dep), so nothing is copied in.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / ".githooks" / "_pre-push-worktree-hygiene.sh"


class TestPrePushWorktreeHygiene(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="pre-push-wt-hygiene-")
        self.repo = Path(self._tmp) / "repo"
        self.repo.mkdir(parents=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "tester")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        # Normalize the default branch name to `main` regardless of the
        # host git's init.defaultBranch.
        self._git("branch", "-M", "main")

    def tearDown(self) -> None:
        # Best-effort worktree teardown before removing the tree.
        self._git("worktree", "prune")
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            check=False,
        )

    def _add_worktree(self, name: str, branch: str, *, extra_commit: bool) -> Path:
        wt = Path(self._tmp) / name
        self._git("worktree", "add", "-b", branch, str(wt), "main")
        if extra_commit:
            (wt / "extra.txt").write_text("e\n", encoding="utf-8")
            self._git("add", "-A", cwd=wt)
            self._git("commit", "-q", "-m", "ahead of main", cwd=wt)
        return wt

    def _run_hook(self, *, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_merged_worktree_is_flagged(self) -> None:
        # No extra commit → branch tip == main tip → merged → orphan.
        self._add_worktree("wt_merged", "feat-merged", extra_commit=False)
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("git worktree remove", r.stderr)
        self.assertIn("feat-merged", r.stderr)
        self.assertIn("wt_merged", r.stderr)

    def test_unmerged_worktree_is_quiet(self) -> None:
        self._add_worktree("wt_active", "feat-active", extra_commit=True)
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)

    def test_detached_worktree_is_ignored(self) -> None:
        wt = Path(self._tmp) / "wt_detached"
        self._git("worktree", "add", "--detach", str(wt))
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)

    def test_run_from_orphan_does_not_self_flag(self) -> None:
        wt = self._add_worktree("wt_merged", "feat-merged", extra_commit=False)
        r = self._run_hook(cwd=wt)
        self.assertEqual(0, r.returncode, r.stderr)
        # self_top == wt → excluded → its own branch is not reported.
        self.assertNotIn("feat-merged", r.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
