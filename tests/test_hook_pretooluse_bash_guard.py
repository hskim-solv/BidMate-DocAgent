"""Regression: PreToolUse bash-guard hook (issue #826 Hook B / #865).

Exercises the two responsibilities of
``scripts/claude-hooks/pretooluse-bash-guard.sh``:

  - **Branch (1)** ``gh pr merge --delete-branch``: smoke-regression that
    other gh commands fall through to ``exit 0`` (the deep merge audit
    requires a real ``gh`` and is exercised by the original PR #423→#431
    incident; not re-asserted here).
  - **Branch (2)** ``gh pr create`` stacked guard (issue #865): the core
    surface added in this PR. Builds a real temp git repo, fakes
    ``refs/remotes/origin/*`` via ``git update-ref``, and verifies the
    block / allow matrix.

The hook is copied into a per-test temp ``REPO_ROOT`` so
``.hook-fires.log`` writes are isolated from the developer's machine.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / "scripts" / "claude-hooks" / "pretooluse-bash-guard.sh"
HOOK_HELPER = REPO / "scripts" / "claude-hooks" / "_bash_guard_parse.py"

_GIT_ENV: dict[str, str] = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class TestPreToolUseBashGuard(unittest.TestCase):
    """Behavioral contract for the bash-guard PreToolUse hook."""

    def setUp(self) -> None:
        # Mirror the production layout (scripts/claude-hooks/ under a
        # repo root) so the hook's ``REPO_ROOT`` resolution and
        # ``.hook-fires.log`` writes target this temp tree.
        self._tmp = tempfile.mkdtemp()
        self._tmp_repo = Path(self._tmp) / "repo"
        (self._tmp_repo / ".claude").mkdir(parents=True)
        (self._tmp_repo / "scripts" / "claude-hooks").mkdir(parents=True)
        shutil.copy(HOOK, self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name)
        # The hook delegates parsing to _bash_guard_parse.py (issue #1045).
        # Copy it alongside so the temp REPO_ROOT resolves the helper.
        shutil.copy(
            HOOK_HELPER, self._tmp_repo / "scripts" / "claude-hooks" / HOOK_HELPER.name
        )
        self._hook = self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name
        self._fires_log = self._tmp_repo / ".claude" / ".hook-fires.log"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, **_GIT_ENV}
        return subprocess.run(
            ["git", "-C", str(self._tmp_repo), *args],
            check=check, capture_output=True, text=True, env=env,
        )

    def _commit(self, name: str, content: str = "x") -> str:
        (self._tmp_repo / name).write_text(content)
        self._git("add", name)
        self._git("commit", "-m", name)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _set_origin_ref(self, branch: str, sha: str) -> None:
        """Fake ``origin/<branch>`` without an actual remote."""
        self._git("update-ref", f"refs/remotes/origin/{branch}", sha)

    def _init_repo(self) -> str:
        """Seed a repo with main = M1 and ``refs/remotes/origin/main``."""
        # ``-b main`` makes the initial branch ``main`` regardless of the
        # user's git defaultBranch config.
        subprocess.run(
            ["git", "init", "-b", "main", str(self._tmp_repo)],
            check=True, capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
        m1 = self._commit("m1.txt", "m1")
        self._set_origin_ref("main", m1)
        return m1

    def _run(self, command: str) -> subprocess.CompletedProcess:
        payload = {"tool_input": {"command": command}}
        return subprocess.run(
            ["bash", str(self._hook)],
            input=json.dumps(payload), text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )

    # ------------------------------------------------------------------
    # Pass-through cases (branch (1) / unrelated commands)
    # ------------------------------------------------------------------

    def test_non_gh_command_is_noop(self) -> None:
        self._init_repo()
        r = self._run("ls -la /tmp")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.assertFalse(self._fires_log.exists())

    def test_other_gh_subcommand_is_noop(self) -> None:
        """``gh repo view`` / ``gh issue list`` etc. fall through."""
        self._init_repo()
        r = self._run("gh repo view hskim-solv/BidMate-DocAgent")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_gh_pr_merge_without_delete_branch_is_noop(self) -> None:
        """``gh pr merge --squash`` (no --delete-branch) falls through."""
        self._init_repo()
        r = self._run("gh pr merge 999 --squash")
        self.assertEqual(r.returncode, 0)

    def test_empty_command_is_noop(self) -> None:
        r = subprocess.run(
            ["bash", str(self._hook)],
            input=json.dumps({"tool_input": {"command": ""}}),
            text=True, capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )
        self.assertEqual(r.returncode, 0)

    # ------------------------------------------------------------------
    # gh pr create — explicit --base bypasses the guard
    # ------------------------------------------------------------------

    def test_create_with_explicit_base_branch_is_allowed(self) -> None:
        """``gh pr create --base feat/A …`` — explicit stack target."""
        self._init_repo()
        r = self._run("gh pr create --base feat/A --title T --body B")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_create_with_base_equals_form_is_allowed(self) -> None:
        """``gh pr create --base=feat/A`` (equals form)."""
        self._init_repo()
        r = self._run("gh pr create --base=feat/A --title T")
        self.assertEqual(r.returncode, 0)

    def test_create_with_explicit_base_main_is_allowed(self) -> None:
        """``--base main`` is the documented escape for intentional flatten."""
        m1 = self._init_repo()
        self._git("checkout", "-b", "feat/A")
        a1 = self._commit("a1.txt", "a1")
        self._set_origin_ref("feat/A", a1)
        self._git("checkout", "-b", "feat/B")
        self._commit("b1.txt", "b1")
        # Even though feat/B is stacked on feat/A, --base main flattens.
        r = self._run("gh pr create --base main --title T")
        self.assertEqual(r.returncode, 0)

    # ------------------------------------------------------------------
    # gh pr create — branch shape decides block vs allow
    # ------------------------------------------------------------------

    def test_create_on_branch_forked_off_main_is_allowed(self) -> None:
        """Branch directly off main — no stack, no block."""
        self._init_repo()
        self._git("checkout", "-b", "feat/issue-1-foo")
        self._commit("f1.txt", "f1")
        r = self._run("gh pr create --title T --body B")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stderr, "")

    def test_create_on_stacked_branch_is_blocked(self) -> None:
        """Branch forked off another open PR's branch — must block."""
        self._init_repo()
        # PR A: feat/A off main
        self._git("checkout", "-b", "feat/A")
        a1 = self._commit("a1.txt", "a1")
        self._set_origin_ref("feat/A", a1)
        # PR B: feat/B off feat/A (the stacking)
        self._git("checkout", "-b", "feat/B")
        self._commit("b1.txt", "b1")
        r = self._run("gh pr create --title T --body B")
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("stacked", r.stderr.lower())
        self.assertIn("feat/A", r.stderr)
        # Hook fires log records the block.
        self.assertTrue(self._fires_log.exists())
        line = self._fires_log.read_text().strip()
        self.assertIn("|blocked|gh-pr-create-stacked|", line)
        self.assertIn("on=feat/A", line)

    def test_block_message_quotes_recovery_options(self) -> None:
        """Operator-facing rationale must surface both recovery paths."""
        self._init_repo()
        self._git("checkout", "-b", "feat/A")
        a1 = self._commit("a1.txt", "a1")
        self._set_origin_ref("feat/A", a1)
        self._git("checkout", "-b", "feat/B")
        self._commit("b1.txt", "b1")
        r = self._run("gh pr create")
        self.assertEqual(r.returncode, 2)
        # Both escape hatches must be discoverable from the stderr alone.
        self.assertIn("--base feat/A", r.stderr)
        self.assertIn("--base main", r.stderr)

    def test_create_without_origin_main_ref_fails_open(self) -> None:
        """Fresh clone / worktree with no origin/main → don't block."""
        # Init repo but skip setting refs/remotes/origin/main.
        subprocess.run(
            ["git", "init", "-b", "main", str(self._tmp_repo)],
            check=True, capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
        self._commit("m1.txt", "m1")
        r = self._run("gh pr create --title T --body B")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_create_when_only_origin_main_exists_is_allowed(self) -> None:
        """Single origin ref = main → no other branches to be stacked on."""
        self._init_repo()
        # We're still on main; pretend a feature branch has been created
        # without any other origin/* refs around. No stack possible.
        self._git("checkout", "-b", "feat/X")
        self._commit("x.txt", "x")
        r = self._run("gh pr create --title T")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_create_with_compound_shell_command_is_caught(self) -> None:
        """``foo && gh pr create`` chained commands are also subject to the guard."""
        self._init_repo()
        self._git("checkout", "-b", "feat/A")
        a1 = self._commit("a1.txt", "a1")
        self._set_origin_ref("feat/A", a1)
        self._git("checkout", "-b", "feat/B")
        self._commit("b1.txt", "b1")
        # Compound command: the shlex-split in the hook walks each `;|&` part.
        r = self._run("echo starting && gh pr create --title T --body B")
        self.assertEqual(r.returncode, 2, msg=r.stderr)


if __name__ == "__main__":
    unittest.main()
