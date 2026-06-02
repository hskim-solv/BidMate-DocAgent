"""Guard: scripts/spawn_track_session.sh — cmux track-session spawn helper (issue #1767).

The helper nests `cmux workspace create --command "claude '<prompt>'"`, whose
single-quoted inner string cannot escape a backtick / $ / ! / " / '. Two guard
families mirror tests/test_test_sh_bash32_regression.py:

  1. Static: the escaping guard, the cmux absolute path, the fixed
     `claude '<prompt>'` (no permission flag), the origin/main base, and the
     SSoT branch validation (no regex copy) must all be present in the source.
  2. Behavioral: run the script with DRY_RUN=1 and a stubbed `cmux` to confirm
     forbidden prompts are rejected (exit 1), `#` is allowed, the in-cmux path
     echoes `workspace create ... --focus false`, and the non-cmux fallback
     prints a manual `claude '<prompt>'` resume line instead of spawning.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "spawn_track_session.sh"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """Source with full-line comments and blank lines stripped.

    The negative guards ("must NOT contain …") below check the executable
    body, not the prose — the comments intentionally *name* `declare -a` and
    `--dangerously-skip-permissions` to document the traps being avoided, so a
    raw substring scan of the whole file would false-positive on them.
    """
    return "\n".join(
        line
        for line in _source().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def _stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestSpawnTrackStatic(unittest.TestCase):
    def test_strict_bash_mode(self) -> None:
        self.assertIn("set -euo pipefail", _source())

    def test_cmux_absolute_path_default(self) -> None:
        self.assertIn("/Applications/cmux.app/Contents/Resources/bin/cmux", _source())

    def test_focus_false_keeps_caller(self) -> None:
        self.assertIn("--focus false", _source())

    def test_permission_is_fixed_no_skip_flag(self) -> None:
        self.assertIn("claude '", _source())  # cold-start command is hardcoded
        self.assertNotIn("--dangerously", _code())  # never injects a skip flag

    def test_base_default_origin_main(self) -> None:
        self.assertIn('BASE="${BASE:-origin/main}"', _source())

    def test_reuses_branch_ssot_not_regex_copy(self) -> None:
        src = _source()
        self.assertIn("check_branch_and_issue.py --branch", src)
        # The branch whitelist regex lives only in the SSoT; never copied here.
        self.assertNotIn("feat|fix|docs", src)

    def test_escape_guard_rejects_five_chars_allows_hash(self) -> None:
        src = _source()
        for needle in ("*'`'*)", "*'$'*)", "*'!'*)", "*'\"'*)", "*\"'\"*)"):
            self.assertIn(needle, src, f"escape guard must cover the case {needle!r}")
        # `#` must NOT be in the reject set (it is safe inside single quotes).
        self.assertNotIn("*'#'*)", src)

    def test_no_declare_a_array(self) -> None:
        # `declare -a` arrays lose PATH in eval contexts (issue #1767 실측).
        self.assertNotIn("declare -a", _code())


class TestSpawnTrackBehavior(unittest.TestCase):
    def _run(self, prompt: str, *, cmux_ok: bool = True, drop_issue: bool = False):
        tmp = tempfile.mkdtemp(prefix="spawn-track-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        binp = Path(tmp)
        # stub `cmux`: `identify` exits 0 (in-cmux) or 1 (outside). Any other
        # subcommand echoes a marker — only reached when DRY_RUN=0, which the
        # tests never use (DRY_RUN=1 echoes the command instead of running it).
        code = "0" if cmux_ok else "1"
        _stub(
            binp / "cmux",
            f'#!/bin/sh\nif [ "$1" = identify ]; then exit {code}; fi\n'
            f'echo "CMUX_STUB:$*"\nexit 0\n',
        )
        env = dict(os.environ)
        env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"
        env["CMUX_BIN"] = str(binp / "cmux")
        env["DRY_RUN"] = "1"  # never touch the real git / cmux
        env["PROMPT"] = prompt
        env["TYPE"] = "chore"
        env["SLUG"] = "demo"
        if drop_issue:
            env.pop("ISSUE", None)
        else:
            env["ISSUE"] = "1767"
        bash = "/bin/bash" if Path("/bin/bash").exists() else "bash"
        return subprocess.run(
            [bash, str(SCRIPT)],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_forbidden_backtick_rejected(self) -> None:
        r = self._run("use `backticks` here")
        self.assertEqual(1, r.returncode)
        self.assertIn("forbidden char", r.stderr)
        self.assertIn("backtick", r.stderr)

    def test_forbidden_apostrophe_rejected(self) -> None:
        r = self._run("don't do this")
        self.assertEqual(1, r.returncode)
        self.assertIn("apostrophe", r.stderr)

    def test_hash_is_allowed(self) -> None:
        r = self._run("close issue #1767 and measure recall")
        self.assertEqual(0, r.returncode, r.stderr)

    def test_in_cmux_echoes_workspace_create(self) -> None:
        r = self._run("measure retrieval recall on real100 v2", cmux_ok=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("workspace create", r.stdout)
        self.assertIn("--focus false", r.stdout)

    def test_fallback_prints_manual_resume_when_not_in_cmux(self) -> None:
        r = self._run("measure retrieval recall", cmux_ok=False)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("claude '", r.stdout)  # manual resume command
        self.assertNotIn("workspace create", r.stdout)  # spawn skipped

    def test_missing_issue_fails(self) -> None:
        r = self._run("measure recall", drop_issue=True)
        self.assertNotEqual(0, r.returncode)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
