"""Regression tests for auto-ship start and review gate helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts" / "claude-hooks"))

import _ship_review_gate as review_gate  # noqa: E402
import _ship_start as ship_start  # noqa: E402


def test_ship_start_slugifies_ascii_title() -> None:
    assert (
        ship_start.slugify("Automate ship start and review gate")
        == "automate-ship-start-and-review-gate"
    )


def test_ship_start_korean_title_needs_explicit_slug() -> None:
    assert ship_start.slugify("이슈 생성부터 머지까지 자동화") == "work"


def test_ship_start_creates_issue_then_switches_branch(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, *, check=True):
        calls.append(list(cmd))
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="https://github.com/hskim-solv/BidMate-DocAgent/issues/1410\n",
            )
        if cmd[:3] == ["git", "switch", "-c"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(ship_start, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "_ship_start.py",
            "--title",
            "Automate ship start and review gate",
            "--type",
            "chore",
            "--no-fetch",
        ],
    )

    assert ship_start.main() == 0
    assert ["git", "fetch", "origin", "main"] not in calls
    assert [
        "git",
        "switch",
        "-c",
        "chore/issue-1410-automate-ship-start-and-review-gate",
        "origin/main",
    ] in calls
    assert "created https://github.com/hskim-solv/BidMate-DocAgent/issues/1410" in capsys.readouterr().out


def test_review_gate_passes_when_open_and_no_review_blockers(monkeypatch, capsys) -> None:
    monkeypatch.setattr(review_gate, "resolve_pr_number", lambda pr: 1410)
    monkeypatch.setattr(
        review_gate,
        "resolve_repo",
        lambda repo: ("hskim-solv/BidMate-DocAgent", "hskim-solv", "BidMate-DocAgent"),
    )
    monkeypatch.setattr(
        review_gate,
        "pr_view",
        lambda pr, repo: {
            "state": "OPEN",
            "isDraft": False,
            "reviewDecision": "",
            "url": "https://github.com/hskim-solv/BidMate-DocAgent/pull/1411",
        },
    )
    monkeypatch.setattr(review_gate, "fetch_unresolved_threads", lambda owner, repo, pr: [])
    monkeypatch.setattr(sys, "argv", ["_ship_review_gate.py", "--pr", "1410"])

    assert review_gate.main() == 0
    assert "no review blockers" in capsys.readouterr().out


def test_review_gate_blocks_requested_changes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(review_gate, "resolve_pr_number", lambda pr: 1410)
    monkeypatch.setattr(
        review_gate,
        "resolve_repo",
        lambda repo: ("hskim-solv/BidMate-DocAgent", "hskim-solv", "BidMate-DocAgent"),
    )
    monkeypatch.setattr(
        review_gate,
        "pr_view",
        lambda pr, repo: {
            "state": "OPEN",
            "isDraft": False,
            "reviewDecision": "CHANGES_REQUESTED",
            "url": "https://github.com/hskim-solv/BidMate-DocAgent/pull/1411",
        },
    )
    monkeypatch.setattr(review_gate, "fetch_unresolved_threads", lambda owner, repo, pr: [])
    monkeypatch.setattr(sys, "argv", ["_ship_review_gate.py", "--pr", "1410"])

    assert review_gate.main() == 1
    assert "CHANGES_REQUESTED" in capsys.readouterr().err


def test_review_gate_blocks_unresolved_threads(monkeypatch, capsys) -> None:
    monkeypatch.setattr(review_gate, "resolve_pr_number", lambda pr: 1410)
    monkeypatch.setattr(
        review_gate,
        "resolve_repo",
        lambda repo: ("hskim-solv/BidMate-DocAgent", "hskim-solv", "BidMate-DocAgent"),
    )
    monkeypatch.setattr(
        review_gate,
        "pr_view",
        lambda pr, repo: {
            "state": "OPEN",
            "isDraft": False,
            "reviewDecision": "",
            "url": "https://github.com/hskim-solv/BidMate-DocAgent/pull/1411",
        },
    )
    monkeypatch.setattr(
        review_gate,
        "fetch_unresolved_threads",
        lambda owner, repo, pr: [
            review_gate.ThreadSummary(
                path="Makefile",
                line=10,
                author="reviewer",
                url="https://example.test/thread",
                body="Please fix this.",
            )
        ],
    )
    monkeypatch.setattr(sys, "argv", ["_ship_review_gate.py", "--pr", "1410"])

    assert review_gate.main() == 1
    err = capsys.readouterr().err
    assert "unresolved review thread" in err
    assert "Makefile:10" in err
