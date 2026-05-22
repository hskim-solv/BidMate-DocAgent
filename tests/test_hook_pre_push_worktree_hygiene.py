"""Regression: pre-push orphan-worktree hygiene (issue #1052, #1163, #1270).

Pins the soft-warn contract (always exit 0; warning only on stderr) for
`.githooks/_pre-push-worktree-hygiene.sh`:

  1. worktree whose branch is merged into main → exit 0, stderr names it
  2. worktree whose branch is NOT merged       → exit 0, stderr quiet
  3. detached-HEAD worktree                     → exit 0, stderr quiet
  4. run from the orphan worktree itself        → exit 0, not self-flagged
  5. SQUASH-merged branch (new SHA on main)     → exit 0, stderr names it
  6. branch with a '[gone]' upstream            → exit 0, stderr names it
  7. gh PR MERGED + opt-in env                  → exit 0, stderr names it
  8. gh PR MERGED but opt-in OFF (default)      → exit 0, stderr quiet
  9. cherry walk capped by divergence (#1270)   → exit 0, walk skipped past cap

Scenarios 5-8 are the #1163 fix: `git branch --merged` only lists ancestor
tips, so squash-merges (this repo's default merge path) were a silent
false-negative. Each scenario runs in an isolated temp git repo with real
`git worktree` checkouts. The hook is pure git (no python dep), so nothing
is copied in.
"""
from __future__ import annotations

import os
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

    def _run_hook(
        self, *, cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def _squash_merge(self, branch: str) -> None:
        # Mimic `gh pr merge --squash`: collapse the branch's commits into a
        # single brand-new commit on main (a SHA the branch tip is NOT an
        # ancestor of), from the primary worktree.
        self._git("merge", "--squash", branch)
        self._git("commit", "-q", "-m", f"squash-merge {branch}")

    def _write_fake_gh(self, merged_branch: str) -> Path:
        # A stub `gh` that reports MERGED only for `pr view <merged_branch>`,
        # so the opt-in (d) signal can be exercised without the network.
        bindir = Path(self._tmp) / "fakebin"
        bindir.mkdir(exist_ok=True)
        gh = bindir / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            f'if [ "$1" = "pr" ] && [ "$2" = "view" ] && [ "$3" = "{merged_branch}" ]; then\n'
            "  echo MERGED\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        return bindir

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

    def test_squash_merged_worktree_is_flagged(self) -> None:
        # #1163: gh pr merge --squash lands a NEW commit on main, so the
        # feature tip is NOT an ancestor and `git branch --merged` missed it.
        # Patch-equivalence (git cherry) must still flag the orphan worktree.
        self._add_worktree("wt_squash", "feat-squash", extra_commit=True)
        self._squash_merge("feat-squash")
        # Guard the premise: the squash is genuinely non-ancestor (else this
        # would silently degrade into the old ancestor-only case).
        anc = self._git("merge-base", "--is-ancestor", "feat-squash", "main")
        self.assertNotEqual(0, anc.returncode, "squash merge must not be an ancestor")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("git worktree remove", r.stderr)
        self.assertIn("feat-squash", r.stderr)
        self.assertIn("wt_squash", r.stderr)

    def test_gone_upstream_worktree_is_flagged(self) -> None:
        # The documented incident: --delete-branch removes the remote branch
        # after merge; once pruned, the local branch tracks a '[gone]'
        # upstream — a stale signal offline can detect without the network.
        remote = Path(self._tmp) / "remote.git"
        self._git("init", "--bare", "-q", str(remote))
        self._git("remote", "add", "origin", str(remote))
        wt = self._add_worktree("wt_gone", "feat-gone", extra_commit=True)
        push = self._git("push", "-u", "origin", "feat-gone", cwd=wt)
        self.assertEqual(0, push.returncode, push.stderr)
        self._git("push", "origin", "--delete", "feat-gone")
        self._git("fetch", "--prune", "origin")
        track = self._git(
            "for-each-ref", "--format=%(upstream:track)", "refs/heads/feat-gone"
        )
        self.assertIn("[gone]", track.stdout, "setup: upstream should be gone")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("feat-gone", r.stderr)
        self.assertIn("wt_gone", r.stderr)

    def test_gh_merged_pr_is_flagged_when_opted_in(self) -> None:
        # Multi-commit squash with a live upstream is the one case (a)-(c)
        # miss; the opt-in (d) gh signal catches it. The branch is genuinely
        # active offline (1 commit ahead, no gone upstream), so only gh flags.
        self._add_worktree("wt_gh", "feat-gh", extra_commit=True)
        bindir = self._write_fake_gh("feat-gh")
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "BIDMATE_WORKTREE_HYGIENE_GH": "1",
        }
        r = self._run_hook(env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("feat-gh", r.stderr)
        self.assertIn("wt_gh", r.stderr)

    def test_cherry_walk_is_capped_by_divergence(self) -> None:
        # #1270: `git cherry` (signal b) is O(commits-ahead) in time AND
        # memory; on branches diverged hundreds of commits past base it spiked
        # memory enough to get the hook OOM-killed mid-push. A cheap
        # rev-list --count pre-check now gates the walk to branches within
        # $cherry_max of base. Force the cap to 0 and confirm the patch-id walk
        # is skipped: a squash-merged branch (only signal b can flag it — it is
        # non-ancestor, has no gone upstream) stays quiet, proving the gate
        # controls the expensive walk.
        self._add_worktree("wt_squash", "feat-squash", extra_commit=True)
        self._squash_merge("feat-squash")
        env = {**os.environ, "BIDMATE_WORKTREE_HYGIENE_CHERRY_MAX": "0"}
        r = self._run_hook(env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        # Walk skipped → signal (b) never fires → branch not flagged.
        self.assertNotIn("feat-squash", r.stderr)

    def test_gh_signal_is_off_by_default(self) -> None:
        # Same setup, fake gh on PATH reports MERGED — but without the opt-in
        # env the offline-active branch stays quiet (pushes stay offline/fast).
        self._add_worktree("wt_gh", "feat-gh", extra_commit=True)
        bindir = self._write_fake_gh("feat-gh")
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        r = self._run_hook(env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
