"""Regression: cross-worktree ADR collision PreToolUse hook (issue #1069).

Exercises ``scripts/claude-hooks/pretooluse-adr-collision.sh``:

  - early-exit gates (non-Write, non-ADR filename, _template.md, existing
    file, malformed JSON) — and that ``gh`` is NOT invoked on those paths.
  - cross-worktree collision detection via PR title AND headRefName,
    zero-pad-insensitive, ignoring PR body.
  - fail-open on empty list / gh network failure.

The hook shells out to ``gh pr list``, which is non-deterministic in CI, so
a fake ``gh`` is written into a temp ``bin/`` and prepended to PATH. The
stub touches a marker file so tests can assert the early-exit gates never
reach the network. The hook is copied into a per-test temp REPO_ROOT so
``.hook-fires.log`` writes stay isolated from the developer's machine.
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
HOOK = REPO / "scripts" / "claude-hooks" / "pretooluse-adr-collision.sh"


class TestPreToolUseAdrCollision(unittest.TestCase):
    """Behavioral contract for the cross-worktree ADR collision hook."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_repo = Path(self._tmp) / "repo"
        (self._tmp_repo / ".claude").mkdir(parents=True)
        (self._tmp_repo / "scripts" / "claude-hooks").mkdir(parents=True)
        (self._tmp_repo / "docs" / "adr").mkdir(parents=True)
        (self._tmp_repo / "src").mkdir(parents=True)
        shutil.copy(HOOK, self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name)
        self._hook = self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name
        self._fires_log = self._tmp_repo / ".claude" / ".hook-fires.log"
        self._bin = self._tmp_repo / "bin"
        self._bin.mkdir()
        self._gh_marker = self._tmp_repo / "gh_called"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _write_gh_stub(self, json_output: str, exit_code: int = 0) -> None:
        """Fake `gh` that records invocation then echoes canned JSON."""
        gh = self._bin / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            f"touch '{self._gh_marker}'\n"
            f"cat <<'JSON'\n{json_output}\nJSON\n"
            f"exit {exit_code}\n"
        )
        gh.chmod(0o755)

    def _gh_was_called(self) -> bool:
        return self._gh_marker.exists()

    def _run(self, file_path: str, tool_name: str = "Write"):
        payload = {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
        env = dict(os.environ)
        env["PATH"] = f"{self._bin}:{env['PATH']}"
        return subprocess.run(
            ["bash", str(self._hook)],
            input=json.dumps(payload), text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo), env=env,
        )

    def _adr_path(self, name: str) -> str:
        return str(self._tmp_repo / "docs" / "adr" / name)

    # ------------------------------------------------------------------
    # early-exit gates — gh must not be reached
    # ------------------------------------------------------------------

    def test_non_write_tool_is_noop(self) -> None:
        self._write_gh_stub('[{"number":1,"title":"ADR 0060","headRefName":"x"}]')
        r = self._run(self._adr_path("0060-x.md"), tool_name="Edit")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.assertFalse(self._gh_was_called())

    def test_non_adr_path_is_noop_and_skips_gh(self) -> None:
        self._write_gh_stub('[{"number":1,"title":"ADR 0060","headRefName":"x"}]')
        r = self._run(str(self._tmp_repo / "src" / "foo.py"))
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self._gh_was_called())

    def test_template_md_excluded(self) -> None:
        self._write_gh_stub('[{"number":1,"title":"ADR 0060","headRefName":"x"}]')
        r = self._run(self._adr_path("_template.md"))
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self._gh_was_called())

    def test_existing_adr_file_is_noop(self) -> None:
        p = self._adr_path("0060-x.md")
        Path(p).write_text("# existing\n")
        self._write_gh_stub('[{"number":1,"title":"ADR 0060","headRefName":"x"}]')
        r = self._run(p)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self._gh_was_called())

    def test_malformed_json_is_noop(self) -> None:
        env = dict(os.environ)
        env["PATH"] = f"{self._bin}:{env['PATH']}"
        r = subprocess.run(
            ["bash", str(self._hook)],
            input="{not json", text=True, capture_output=True, check=False,
            cwd=str(self._tmp_repo), env=env,
        )
        self.assertEqual(r.returncode, 0)

    # ------------------------------------------------------------------
    # collision detection — block (exit 2)
    # ------------------------------------------------------------------

    def test_collision_via_pr_title_blocks(self) -> None:
        self._write_gh_stub(
            '[{"number":900,"title":"ADR 0060 foo","headRefName":"feat/x"}]'
        )
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("900", r.stderr)
        self.assertIn("0060", r.stderr)
        self.assertTrue(self._fires_log.exists())
        line = self._fires_log.read_text().strip()
        self.assertIn("|blocked|adr-collision|", line)
        self.assertIn("0060-mine.md", line)
        self.assertIn("open_pr=900", line)

    def test_collision_via_branch_name_blocks(self) -> None:
        # title lacks the number; only the head branch reserves it.
        self._write_gh_stub(
            '[{"number":901,"title":"sync stuff","headRefName":"docs/issue-5-adr-0060-foo"}]'
        )
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("901", r.stderr)

    def test_zero_pad_insensitive_match_blocks(self) -> None:
        self._write_gh_stub('[{"number":902,"title":"ADR-60 thing","headRefName":"x"}]')
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("902", r.stderr)

    # ------------------------------------------------------------------
    # no collision / fail-open — pass (exit 0)
    # ------------------------------------------------------------------

    def test_different_number_no_collision(self) -> None:
        self._write_gh_stub('[{"number":903,"title":"ADR 0058 other","headRefName":"x"}]')
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertFalse(self._fires_log.exists())

    def test_empty_pr_list_is_noop(self) -> None:
        self._write_gh_stub("[]")
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 0)

    def test_gh_failure_fails_open(self) -> None:
        # network error / no token surfaces as a non-zero gh exit → pass.
        self._write_gh_stub("", exit_code=1)
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 0)

    def test_body_only_mention_is_ignored(self) -> None:
        # title + branch clean. The hook never reads PR body, so a PR that
        # only references 0060 in its body must NOT block (false-positive guard).
        self._write_gh_stub(
            '[{"number":904,"title":"unrelated change","headRefName":"feat/foo"}]'
        )
        r = self._run(self._adr_path("0060-mine.md"))
        self.assertEqual(r.returncode, 0, msg=r.stderr)


if __name__ == "__main__":
    unittest.main()
