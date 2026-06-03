"""Guard: ship-start overlap-preflight gate (issue #1836).

``scripts/claude-hooks/_ship_start.py`` runs ``overlap-preflight`` between the
``git fetch origin main`` and the ``git switch -c`` so a brand-new shipping
branch is not cut on a stale base. The gate's policy (decision 2 of the plan):

  * a base-staleness blocker (local HEAD does not contain origin/main) is a
    hard BLOCK (non-zero exit) — it is gh-independent and deterministic — unless
    ``--overlap-ack`` / ``OVERLAP=ack`` is supplied;
  * path / open-PR overlap *warnings* print and the branch is still created;
  * a scan-process error (gh down / offline / non-zero exit that is not a
    staleness block) fails OPEN — overlap-preflight is a read-only advisory and
    must never hard-fail a fresh task on transient git/gh state
    (memory feedback_merge_admin_gate §7);
  * ``--no-overlap-check`` skips the gate entirely (mirrors ``--no-fetch``).

The script shells out to ``git`` and ``gh`` (non-deterministic in CI), so both
are replaced by Python stubs on PATH whose behavior is driven by env vars the
test sets. The stubs dispatch on argv exactly like
tests/test_hook_pretooluse_adr_collision.py's fake ``gh``. The script is run
from the real repo root so ``python3 scripts/agent_loop.py overlap-preflight``
resolves the real implementation under test.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIP_START = REPO / "scripts" / "claude-hooks" / "_ship_start.py"


GIT_STUB = r'''#!/usr/bin/env python3
import os, sys

argv = sys.argv[1:]
# `git -C <path> ...` — drop the -C pair, it does not change our canned answers.
if len(argv) >= 2 and argv[0] == "-C":
    argv = argv[2:]

stale = os.environ.get("STUB_STALE_BASE") == "1"

def out(s=""):
    sys.stdout.write(s)
    if s and not s.endswith("\n"):
        sys.stdout.write("\n")

if not argv:
    sys.exit(0)
cmd = argv[0]

if cmd == "status":
    # ensure_clean_worktree (no -- args) -> clean; path-scan (-- <paths>) -> clean.
    sys.exit(0)
if cmd == "fetch":
    sys.exit(0)
if cmd == "switch":
    # branch creation — record it so the test can assert it happened.
    marker = os.environ.get("STUB_SWITCH_MARKER")
    if marker:
        open(marker, "a").write(" ".join(argv) + "\n")
    sys.exit(0)
if cmd == "rev-parse":
    ref = argv[-1]
    if ref == "HEAD":
        out("head1111")
    elif ref == "origin/main":
        out("new2222" if stale else "head1111")
    else:
        out("ref0000")
    sys.exit(0)
if cmd == "merge-base":
    # `merge-base --is-ancestor origin/main HEAD` -> exit 0 means HEAD contains
    # origin/main. Stale base => non-zero.
    sys.exit(1 if stale else 0)
if cmd == "worktree":
    # `worktree list --porcelain` — a single self entry on the current branch.
    if len(argv) >= 2 and argv[1] == "list":
        out("worktree %s" % os.getcwd())
        out("HEAD head1111")
        out("branch refs/heads/chore/issue-4242-demo")
        out("")
    sys.exit(0)
if cmd == "ls-remote":
    # no remote issue branches
    sys.exit(0)
if cmd == "rev-list":
    out("0")
    sys.exit(0)
# default: succeed quietly
sys.exit(0)
'''


GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]

def out(s):
    sys.stdout.write(s)

if not argv:
    sys.exit(0)

# `gh issue create ...` -> print an issue URL ship-start parses for the number.
if argv[0] == "issue" and len(argv) >= 2 and argv[1] == "create":
    out("https://github.com/acme/repo/issues/4242\n")
    sys.exit(0)

# `gh issue view <n> --json ...` (overlap-preflight) -> an OPEN issue.
if argv[0] == "issue" and len(argv) >= 2 and argv[1] == "view":
    out(json.dumps({"number": 4242, "title": "demo", "state": "OPEN",
                    "url": "https://github.com/acme/repo/issues/4242"}))
    sys.exit(0)

# `gh issue edit ...` (label apply) -> succeed.
if argv[0] == "issue" and len(argv) >= 2 and argv[1] == "edit":
    sys.exit(0)

# `gh pr list ...` (overlap-preflight open + branch history).
if argv[0] == "pr" and len(argv) >= 2 and argv[1] == "list":
    if os.environ.get("STUB_GH_DOWN") == "1":
        sys.stderr.write("gh: could not connect\n")
        sys.exit(1)
    prs = json.loads(os.environ.get("STUB_OPEN_PRS", "[]"))
    # branch-history query (`--head <branch>`) -> always empty for a fresh branch.
    if "--head" in argv:
        out("[]")
        sys.exit(0)
    out(json.dumps(prs))
    sys.exit(0)

sys.exit(0)
'''


class TestShipStartOverlapGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="ship-start-gate-")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._bin = Path(self._tmp) / "bin"
        self._bin.mkdir()
        self._write_stub("git", GIT_STUB)
        self._write_stub("gh", GH_STUB)
        self._switch_marker = Path(self._tmp) / "switch_called"

    def _write_stub(self, name: str, body: str) -> None:
        p = self._bin / name
        p.write_text(body, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run(self, *extra_args: str, stale: bool = False, gh_down: bool = False,
             open_prs: list | None = None, overlap_ack_env: bool = False):
        env = dict(os.environ)
        # Stub git/gh win over the real ones.
        env["PATH"] = f"{self._bin}{os.pathsep}{env['PATH']}"
        env["STUB_SWITCH_MARKER"] = str(self._switch_marker)
        if stale:
            env["STUB_STALE_BASE"] = "1"
        if gh_down:
            env["STUB_GH_DOWN"] = "1"
        if open_prs is not None:
            env["STUB_OPEN_PRS"] = json.dumps(open_prs)
        if overlap_ack_env:
            env["OVERLAP"] = "ack"
        return subprocess.run(
            ["python3", str(SHIP_START), "--title", "demo", "--type", "chore",
             "--slug", "demo", *extra_args],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _switched(self) -> bool:
        return self._switch_marker.exists()

    # -- staleness BLOCK --------------------------------------------------

    def test_stale_base_blocks_branch_creation(self) -> None:
        r = self._run(stale=True)
        self.assertNotEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertIn("origin/main", (r.stdout + r.stderr))
        self.assertFalse(self._switched(), "branch must NOT be created on a stale base")

    def test_stale_base_with_ack_flag_warns_and_continues(self) -> None:
        r = self._run("--overlap-ack", stale=True)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched(), "ack must let the branch be created")

    def test_stale_base_with_ack_env_warns_and_continues(self) -> None:
        r = self._run(stale=True, overlap_ack_env=True)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched())

    # -- fresh base / warnings continue -----------------------------------

    def test_fresh_base_creates_branch(self) -> None:
        r = self._run(stale=False)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched())

    def test_path_overlap_warns_but_continues(self) -> None:
        # An unrelated open PR touches a load-bearing path. Fresh base, so the
        # gate must warn (path scope is warn-only) and still create the branch.
        prs = [{"number": 77, "title": "other", "headRefName": "feat/issue-9-x",
                "state": "OPEN", "files": [{"path": "rag_core.py"}]}]
        r = self._run("--paths", "rag_core.py", open_prs=prs)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched())

    # -- fail-open on scan error ------------------------------------------

    def test_gh_down_fails_open_and_creates_branch(self) -> None:
        # gh errors during overlap-preflight -> a blocker is recorded but it is
        # NOT a staleness block, so ship-start must fail open and proceed.
        r = self._run(gh_down=True, stale=False)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched())

    # -- full bypass ------------------------------------------------------

    def test_no_overlap_check_skips_gate_even_when_stale(self) -> None:
        r = self._run("--no-overlap-check", stale=True)
        self.assertEqual(0, r.returncode, msg=r.stdout + r.stderr)
        self.assertTrue(self._switched())


if __name__ == "__main__":
    unittest.main()
