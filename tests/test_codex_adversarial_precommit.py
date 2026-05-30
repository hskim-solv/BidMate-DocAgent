from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_codex_adversarial_precommit as precommit


def _proc(payload: dict[str, object], rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["node", "codex-companion.mjs"],
        returncode=rc,
        stdout=json.dumps(payload),
        stderr="",
    )


def _approve() -> dict[str, object]:
    return {
        "result": {
            "verdict": "approve",
            "summary": "clean",
            "findings": [],
            "next_steps": [],
        },
        "parseError": None,
    }


def _needs_attention() -> dict[str, object]:
    return {
        "result": {
            "verdict": "needs-attention",
            "summary": "contract problem",
            "findings": [
                {
                    "severity": "high",
                    "title": "staged issue",
                    "body": "The staged change breaks the contract.",
                    "file": "rag_core.py",
                    "line_start": 10,
                    "line_end": 12,
                    "recommendation": "Fix before committing.",
                }
            ],
            "next_steps": ["fix it"],
        },
        "parseError": None,
    }


def test_load_bearing_hits_reuses_governance_paths():
    assert precommit.load_bearing_hits(["README.md", "rag_core.py", "docs/adr/0066-x.md"]) == [
        "rag_core.py",
        "docs/adr/0066-x.md",
    ]


def test_default_out_dir_uses_actual_git_dir(monkeypatch):
    def fake_run_git(args):
        assert args == ["rev-parse", "--git-dir"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="/tmp/worktree-gitdir\n", stderr="")

    monkeypatch.setattr(precommit, "_run_git", fake_run_git)

    assert precommit.default_out_dir() == Path("/tmp/worktree-gitdir/codex-adversarial-precommit")


def test_build_focus_forces_staged_diff_scope():
    focus = precommit.build_focus(
        hits=["rag_core.py"],
        changed_files=["rag_core.py", "README.md"],
        attempt=2,
        attempts=3,
    )
    assert "git diff --cached" in focus
    assert "Attempt 2/3" in focus
    assert "rag_core.py" in focus
    assert "README.md" in focus


def test_run_precommit_review_requires_every_attempt_to_approve(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, timeout_sec):
        calls.append(list(cmd))
        assert timeout_sec == 900
        return _proc(_approve())

    rc = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        runner=runner,
    )

    assert rc == 0
    assert len(calls) == 2
    assert "Attempt 1/2" in calls[0][-1]
    assert "Attempt 2/2" in calls[1][-1]
    assert (tmp_path / "attempt-1.md").exists()
    assert (tmp_path / "attempt-2.md").exists()


def test_run_precommit_review_blocks_on_needs_attention(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, timeout_sec):
        calls.append(list(cmd))
        return _proc(_needs_attention())

    rc = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        runner=runner,
    )

    assert rc == 1
    assert len(calls) == 1
    rendered = (tmp_path / "attempt-1.md").read_text(encoding="utf-8")
    assert "needs-attention" in rendered
    assert "staged issue" in rendered


def test_run_precommit_review_nonblocking_on_companion_failure(tmp_path: Path):
    """ADR 0089: a companion/codex run failure (rc!=0) is INFRA, not a verdict —
    it must WARN and allow the commit (deferring review to CI), not hard-block."""

    def runner(cmd, timeout_sec):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=127,
            stdout="{}",
            stderr="companion missing",
        )

    rc = precommit.run_precommit_review(
        attempts=1,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        runner=runner,
    )

    assert rc == 0  # infra failure → non-blocking (was rc==1 before ADR 0089)
    assert "companion missing" in (tmp_path / "attempt-1.md").read_text(encoding="utf-8")


def test_run_precommit_review_nonblocking_on_auth_parse_error(tmp_path: Path):
    """ADR 0089 regression: the real incident — codex refresh-token race yields a
    parseError (no verdict). This is INFRA and must not block the commit."""

    def _auth_error() -> dict[str, object]:
        return {
            "result": None,
            "parseError": (
                "Your access token could not be refreshed because your refresh "
                "token was already used. Please log out and sign in again."
            ),
        }

    calls: list[list[str]] = []

    def runner(cmd, timeout_sec):
        calls.append(list(cmd))
        return _proc(_auth_error(), rc=1)

    rc = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        runner=runner,
    )

    assert rc == 0  # auth parseError is infra → non-blocking, deferred to CI
    assert len(calls) == 2  # both attempts tried before giving up (non-blocking)


def test_run_precommit_review_rejects_zero_attempts(tmp_path: Path):
    with pytest.raises(ValueError, match="attempts"):
        precommit.run_precommit_review(
            attempts=0,
            base="HEAD",
            scope="branch",
            companion=Path("/tmp/codex-companion.mjs"),
            changed_files=["rag_core.py"],
            hits=["rag_core.py"],
            out_dir=tmp_path,
            timeout_sec=900,
            runner=lambda cmd, timeout_sec: _proc(_approve()),
        )


def test_run_precommit_review_nonblocking_on_timeout(tmp_path: Path):
    """ADR 0089: a timeout is INFRA (codex could not finish) — WARN and allow the
    commit (review deferred to CI), not hard-block."""

    def runner(cmd, timeout_sec):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout_sec)

    rc = precommit.run_precommit_review(
        attempts=1,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=7,
        runner=runner,
    )

    assert rc == 0  # timeout is infra → non-blocking (was rc==1 before ADR 0089)
    rendered = (tmp_path / "attempt-1.md").read_text(encoding="utf-8")
    assert "timed out after 7s" in rendered
