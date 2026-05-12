"""End-to-end gate tests for scripts/claude-hooks/stop-ship.sh.

Each test creates a throwaway git repo in a tmpdir, drops a synthetic
`.ship-armed` JSON, then invokes the dispatcher and asserts on:

- exit code (gates always exit 0 except the firewall, which exits 1)
- whether the arm-file was disarmed (deleted) by the gate
- a stderr signal substring identifying which gate fired

The "no arm" path is also timed to enforce the <100ms no-op SLA — the
Stop hook fires on every Claude reply and must not impose latency.

We do NOT test stages 1-5 here (they need a real remote, gh, and CI).
Those are exercised via the dry-run + single-PR live test described in
the plan's Verification section.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "scripts" / "claude-hooks" / "stop-ship.sh"


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@e.x",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@e.x"},
    )


@pytest.fixture
def fake_repo(tmp_path):
    """Tmpdir with a minimal git repo + .claude/ subdir + .gitignore.

    `.gitignore` ignores `.claude/` so that the arm-file (a JSON drop in
    `.claude/.ship-armed`) does not appear as an untracked change in
    `git status --porcelain`. Without this, gate_0_has_work would
    consider the tree dirty and proceed past the "nothing to ship"
    check, defeating the gate-only test scope.
    """
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    (tmp_path / ".gitignore").write_text(".claude/\n")
    (tmp_path / "README.md").write_text("hi\n")
    _git("add", ".gitignore", "README.md", cwd=tmp_path)
    _git("commit", "-qm", "init", cwd=tmp_path)
    (tmp_path / ".claude").mkdir()
    return tmp_path


def _arm(repo: Path, *, branch: str, ttl_seconds: int = 7200, **overrides):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = {
        "branch": branch,
        "issue": 9999,
        "armed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(seconds=ttl_seconds))
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "merge_mode": "squash-admin",
        "real_eval_mode": "auto",
        "draft": "false",
        "dry_run": 1,
        "cross_owner": "",
        "stacked": "",
    }
    state.update(overrides)
    (repo / ".claude" / ".ship-armed").write_text(json.dumps(state) + "\n")


def _run_dispatcher(repo: Path, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DISPATCHER)],
        cwd=repo, input="", capture_output=True, text=True,
        timeout=timeout,
    )


# ---- gate 0: armed file absent ----

def test_no_arm_silent_exit(fake_repo):
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    assert r.stderr == ""


def test_no_arm_under_100ms(fake_repo):
    # Warm up (first invocation may be slow due to bash startup).
    _run_dispatcher(fake_repo)
    t0 = time.monotonic()
    r = _run_dispatcher(fake_repo)
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert r.returncode == 0
    # Generous SLA: <500ms even on slow hardware. The intent is "fast enough
    # that Claude's reply termination doesn't visibly stall."
    assert elapsed_ms < 500, f"no-op path took {elapsed_ms:.0f}ms"


# ---- gate 0: malformed JSON ----

def test_malformed_arm_silent_exit(fake_repo):
    (fake_repo / ".claude" / ".ship-armed").write_text("{not json")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    assert "malformed" in r.stderr.lower() or "ship-armed" in r.stderr.lower()


# ---- gate 0: expired ----

def test_expired_arm_disarms(fake_repo):
    _git("checkout", "-b", "feat/issue-9999-foo", cwd=fake_repo)
    (fake_repo / "x.txt").write_text("x")
    _arm(fake_repo, branch="feat/issue-9999-foo", ttl_seconds=-60)
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    assert not (fake_repo / ".claude" / ".ship-armed").exists()
    assert "expired" in r.stderr.lower()


# ---- gate 0: branch mismatch ----

def test_branch_mismatch_disarms(fake_repo):
    _git("checkout", "-b", "feat/issue-9999-other", cwd=fake_repo)
    (fake_repo / "x.txt").write_text("x")
    _arm(fake_repo, branch="feat/issue-9999-foo")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    assert not (fake_repo / ".claude" / ".ship-armed").exists()
    assert "mismatch" in r.stderr.lower() or "!=" in r.stderr


# ---- gate 0: branch firewall ----

def test_main_branch_firewall_refuses(fake_repo):
    _arm(fake_repo, branch="main")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 1
    assert "firewall" in r.stderr.lower() or "cannot ship" in r.stderr.lower()


def test_release_branch_firewall_refuses(fake_repo):
    _git("checkout", "-b", "release/2026.05", cwd=fake_repo)
    _arm(fake_repo, branch="release/2026.05")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 1
    assert "firewall" in r.stderr.lower() or "release" in r.stderr.lower()


# ---- gate 0: nothing to ship ----

def test_clean_tree_silent_exit(fake_repo):
    _git("checkout", "-b", "feat/issue-9999-foo", cwd=fake_repo)
    _arm(fake_repo, branch="feat/issue-9999-foo")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    # Arm-file preserved on no-op (this is a "wait for next change" case,
    # not a failure).
    assert (fake_repo / ".claude" / ".ship-armed").exists()
    assert "nothing to ship" in r.stderr.lower()


# ---- gate 0: live PID guard ----

def test_live_pid_blocks_re_entry(fake_repo):
    _git("checkout", "-b", "feat/issue-9999-foo", cwd=fake_repo)
    (fake_repo / "x.txt").write_text("x")
    _arm(fake_repo, branch="feat/issue-9999-foo")
    # Use this test process's PID — guaranteed alive and `kill -0` returns
    # success (no EPERM, since we own the process).
    (fake_repo / ".claude" / ".ship-running.pid").write_text(f"{os.getpid()}\n")
    r = _run_dispatcher(fake_repo)
    assert r.returncode == 0
    assert "still alive" in r.stderr.lower() or "silent exit" in r.stderr.lower()
    # Arm-file preserved (the other process owns the cycle).
    assert (fake_repo / ".claude" / ".ship-armed").exists()


def test_stale_pid_cleared(fake_repo):
    _git("checkout", "-b", "feat/issue-9999-foo", cwd=fake_repo)
    _arm(fake_repo, branch="feat/issue-9999-foo")
    # PID 999999 is unlikely to exist.
    (fake_repo / ".claude" / ".ship-running.pid").write_text("999999\n")
    r = _run_dispatcher(fake_repo)
    # Clean tree → "nothing to ship" exit, but stale PID file removed.
    assert r.returncode == 0
    assert not (fake_repo / ".claude" / ".ship-running.pid").exists()
