"""Regression: SessionStart worktree hygiene hook (ADR 0096, issue #1783).

The SessionStart hook `scripts/claude-hooks/sessionstart-worktree-hygiene.sh`
delegates to `make worktree-cleanup` to clean the PREVIOUS session's merged
clean orphan worktrees. It must:

  A. remove a merged clean orphan worktree AND delete its local branch, while
     protecting the current (self) worktree and any dirty orphan — the 3-guard
     regression that matters most (self-skip / clean-only / 4-signal merge).
  B. be registered in `.claude/settings.json` under a valid SessionStart hook.
  C. be documented in ship-pr SKILL.md (current-worktree limitation + ADR 0096).
  D. delegate to `make worktree-cleanup` (the SSoT flag combination) + stay soft.

Test A runs the hook through the full chain (hook → make → hygiene script) in
an isolated temp repo with real `git worktree` checkouts, so it exercises the
exact delegation a real session start performs. The hook is invoked from the
`wt_self` checkout so that REPO_ROOT resolves to it — i.e. wt_self plays the
"current session" worktree that must be self-skipped.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / "scripts" / "claude-hooks" / "sessionstart-worktree-hygiene.sh"
HYGIENE = REPO / ".githooks" / "_pre-push-worktree-hygiene.sh"
SETTINGS = REPO / ".claude" / "settings.json"
SHIP_PR_SKILL = REPO / ".claude" / "skills" / "ship-pr" / "SKILL.md"


class TestSessionStartWorktreeHygiene(unittest.TestCase):
    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            check=False,
        )

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sessionstart-wt-hygiene-")
        self.repo = Path(self._tmp) / "repo"
        (self.repo / "scripts" / "claude-hooks").mkdir(parents=True)
        (self.repo / ".githooks").mkdir(parents=True)
        # Copy the real hook + hygiene script so the full chain runs end-to-end.
        shutil.copy(HOOK, self.repo / "scripts" / "claude-hooks" / HOOK.name)
        shutil.copy(HYGIENE, self.repo / ".githooks" / HYGIENE.name)
        # Minimal Makefile mirroring the real worktree-cleanup flag combo. The
        # real target's flags are pinned separately by test D against REPO's
        # Makefile; here we only need the delegation target to exist.
        (self.repo / "Makefile").write_text(
            "worktree-cleanup:\n"
            "\t@bash .githooks/_pre-push-worktree-hygiene.sh "
            "--clean --prune --delete-branches\n"
            "\n"
            "worktree-cleanup-dry-run:\n"
            "\t@bash .githooks/_pre-push-worktree-hygiene.sh "
            "--clean --dry-run --delete-branches\n",
            encoding="utf-8",
        )
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "tester")
        self._git("config", "commit.gpgsign", "false")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        self._git("branch", "-M", "main")

    def tearDown(self) -> None:
        self._git("worktree", "prune")
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _add_worktree(
        self, name: str, branch: str, *, dirty: bool = False
    ) -> Path:
        # No extra commit → branch tip == main tip → merged (ancestor signal).
        wt = Path(self._tmp) / name
        self._git("worktree", "add", "-b", branch, str(wt), "main")
        if dirty:
            (wt / "untracked.txt").write_text("local work\n", encoding="utf-8")
        return wt

    def test_sessionstart_removes_merged_protects_self_and_dirty(self) -> None:
        wt_self = self._add_worktree("wt_self", "feat-self")
        wt_merged = self._add_worktree("wt_merged", "feat-merged")
        wt_dirty = self._add_worktree("wt_dirty", "feat-dirty", dirty=True)

        # Invoke the hook from wt_self's own checkout so REPO_ROOT == wt_self.
        hook = wt_self / "scripts" / "claude-hooks" / HOOK.name
        r = subprocess.run(
            ["bash", str(hook)],
            cwd=str(wt_self),
            capture_output=True,
            text=True,
            check=False,
        )

        # Soft contract: session start is never blocked.
        self.assertEqual(0, r.returncode, r.stderr)

        # Merged clean orphan: worktree removed AND local branch deleted.
        self.assertFalse(wt_merged.exists(), r.stderr)
        gone = self._git("show-ref", "--verify", "refs/heads/feat-merged")
        self.assertNotEqual(0, gone.returncode, "merged branch should be deleted")

        # self-skip guard: the current (cwd) worktree + branch survive.
        self.assertTrue(wt_self.exists())
        self_branch = self._git("show-ref", "--verify", "refs/heads/feat-self")
        self.assertEqual(0, self_branch.returncode, "self branch must survive")

        # clean-only guard: the dirty orphan + branch survive.
        self.assertTrue(wt_dirty.exists())
        dirty_branch = self._git("show-ref", "--verify", "refs/heads/feat-dirty")
        self.assertEqual(0, dirty_branch.returncode, "dirty orphan branch must survive")

    def test_sessionstart_settings_registered(self) -> None:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))  # also pins valid JSON
        hooks = data.get("hooks", {})
        self.assertIn("SessionStart", hooks, "SessionStart key must exist")
        cmds = [
            h.get("command", "")
            for group in hooks["SessionStart"]
            for h in group.get("hooks", [])
        ]
        self.assertTrue(
            any("sessionstart-worktree-hygiene.sh" in c for c in cmds),
            f"SessionStart must invoke the hygiene hook: {cmds}",
        )

    def test_sessionstart_hook_delegates_to_make_and_is_soft(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        self.assertIn("make worktree-cleanup", body, "hook must delegate to the make SSoT")
        self.assertIn("set -u", body)
        self.assertIn("exit 0", body)
        # The real Makefile target must carry the --delete-branches flag (PR1),
        # so the hook's delegation actually deletes merged branches.
        mk = (REPO / "Makefile").read_text(encoding="utf-8")
        self.assertRegex(
            mk,
            r"worktree-cleanup:\s*\n\s*@bash \.githooks/_pre-push-worktree-hygiene\.sh "
            r"--clean --prune --delete-branches",
        )

    def test_sessionstart_skill_documents_current_worktree_limit(self) -> None:
        skill = SHIP_PR_SKILL.read_text(encoding="utf-8")
        self.assertIn("worktree-cleanup", skill)
        self.assertIn("current worktree", skill.lower())
        self.assertIn("0096", skill)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
