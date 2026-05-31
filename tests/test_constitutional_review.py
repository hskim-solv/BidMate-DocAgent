"""Tests for the CODEOWNERS-based constitutional-change gate (ADR 0091).

The gate replaces the author-writable `[constitutional-change-ack]` PR-body
marker with a CODEOWNERS code-owner (≠ PR author) APPROVED review — the trusted
signal the autonomous staging self-ship loop physically cannot self-produce
(GitHub blocks self-approval).

The pure decision function `requires_owner_approval_violation` is tested with no
network; the gh-fetching CLI path is exercised with an injected `gh_json` seam.
A parity test pins `PROTECTED_PATHS` against `.github/CODEOWNERS` so they cannot
drift, and a workflow-lint test confirms the YAML no longer uses the old marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import check_constitutional_review as ccr  # noqa: E402


AUTHOR = "bidmate-loop"
OWNER = "hskim-solv"
OWNERS = {OWNER}
A_PROTECTED = "scripts/_staging_ship.py"
A_NON_PROTECTED = "rag_core.py"


# ---- requires_owner_approval_violation: 5 decision paths ------------------


def test_no_protected_file_touched_returns_none():
    """(a) No protected file in the diff → no violation regardless of reviews."""
    result = ccr.requires_owner_approval_violation(
        changed_files=[A_NON_PROTECTED, "README.md"],
        author_login=AUTHOR,
        approved_reviewer_logins=[],
        owner_logins=OWNERS,
    )
    assert result is None


def test_protected_touched_owner_non_author_approved_returns_none():
    """(b) Protected touched + a code owner (≠ author) approved → ok."""
    result = ccr.requires_owner_approval_violation(
        changed_files=[A_PROTECTED, A_NON_PROTECTED],
        author_login=AUTHOR,
        approved_reviewer_logins=[OWNER],
        owner_logins=OWNERS,
    )
    assert result is None


def test_protected_touched_only_author_approved_is_violation():
    """(c) Protected touched + only the AUTHOR 'approved' → violation.

    Even when the author is somehow listed as an owner, the author is
    defensively excluded — the autonomous loop must not self-approve.
    """
    result = ccr.requires_owner_approval_violation(
        changed_files=[A_PROTECTED],
        author_login=AUTHOR,
        approved_reviewer_logins=[AUTHOR],
        owner_logins={AUTHOR, OWNER},  # author IS an owner here
    )
    assert result is not None
    assert A_PROTECTED in result
    assert "ADR 0091" in result


def test_protected_touched_non_owner_approved_is_violation():
    """(d) Protected touched + a NON-owner approved → violation."""
    result = ccr.requires_owner_approval_violation(
        changed_files=[A_PROTECTED],
        author_login=AUTHOR,
        approved_reviewer_logins=["some-random-contributor"],
        owner_logins=OWNERS,
    )
    assert result is not None
    assert A_PROTECTED in result


def test_protected_touched_no_approvals_is_violation():
    """(e) Protected touched + zero approvals → violation."""
    result = ccr.requires_owner_approval_violation(
        changed_files=[A_PROTECTED],
        author_login=AUTHOR,
        approved_reviewer_logins=[],
        owner_logins=OWNERS,
    )
    assert result is not None
    assert A_PROTECTED in result


def test_codeowners_itself_is_protected():
    """Editing CODEOWNERS without a non-author owner approval is a violation."""
    result = ccr.requires_owner_approval_violation(
        changed_files=[".github/CODEOWNERS"],
        author_login=AUTHOR,
        approved_reviewer_logins=[],
        owner_logins=OWNERS,
    )
    assert result is not None
    assert ".github/CODEOWNERS" in result


# ---- PROTECTED_PATHS ↔ CODEOWNERS parity ----------------------------------


def test_protected_paths_match_codeowners_patterns():
    """The script's PROTECTED_PATHS must equal the CODEOWNERS pattern set.

    Guards against the two sources drifting: every CODEOWNERS data-line pattern
    (leading `/` stripped) is a PROTECTED_PATHS entry and vice versa.
    """
    codeowners_text = (ROOT_DIR / ".github" / "CODEOWNERS").read_text(
        encoding="utf-8"
    )
    patterns = ccr.codeowners_protected_patterns(codeowners_text)
    assert patterns == set(ccr.PROTECTED_PATHS), (
        "PROTECTED_PATHS and .github/CODEOWNERS have drifted:\n"
        f"  only in CODEOWNERS: {patterns - set(ccr.PROTECTED_PATHS)}\n"
        f"  only in PROTECTED_PATHS: {set(ccr.PROTECTED_PATHS) - patterns}"
    )


def test_codeowners_owner_is_parsed():
    """The owner login appears in the parsed CODEOWNERS owner pool."""
    codeowners_text = (ROOT_DIR / ".github" / "CODEOWNERS").read_text(
        encoding="utf-8"
    )
    logins = ccr.parse_codeowners_logins(codeowners_text)
    assert OWNER in logins


# ---- CLI path with an injected gh_json seam (no network) ------------------


def _fake_gh_json(changed, author, approved):
    """Build a gh_json stub returning fixture JSON for the three api calls."""
    import json

    def _run(args: list[str]) -> str:
        joined = " ".join(args)
        if "/files" in joined:
            return "".join(f"{f}\n" for f in changed)
        if "/reviews" in joined:
            return json.dumps(approved)
        # the `pulls/{pr}` author lookup
        return author + "\n"

    return _run


def test_check_pr_mode_ok_when_owner_approved(monkeypatch, tmp_path):
    monkeypatch.setattr(ccr, "gh_available", lambda: True)
    monkeypatch.setattr(ccr, "get_repo_slug", lambda: "hskim-solv/BidMate-DocAgent")
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text(f"{A_PROTECTED} @{OWNER}\n", encoding="utf-8")
    rc = ccr.check_pr_mode(
        42,
        codeowners_path=str(codeowners),
        gh_json=_fake_gh_json([A_PROTECTED], AUTHOR, [OWNER]),
    )
    assert rc == 0


def test_check_pr_mode_violation_when_only_author_approved(monkeypatch, tmp_path):
    monkeypatch.setattr(ccr, "gh_available", lambda: True)
    monkeypatch.setattr(ccr, "get_repo_slug", lambda: "hskim-solv/BidMate-DocAgent")
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text(f"{A_PROTECTED} @{OWNER}\n", encoding="utf-8")
    rc = ccr.check_pr_mode(
        42,
        codeowners_path=str(codeowners),
        gh_json=_fake_gh_json([A_PROTECTED], AUTHOR, [AUTHOR]),
    )
    assert rc == 1


def test_check_pr_mode_ok_when_no_protected_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ccr, "gh_available", lambda: True)
    monkeypatch.setattr(ccr, "get_repo_slug", lambda: "hskim-solv/BidMate-DocAgent")
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text(f"{A_PROTECTED} @{OWNER}\n", encoding="utf-8")
    rc = ccr.check_pr_mode(
        42,
        codeowners_path=str(codeowners),
        gh_json=_fake_gh_json([A_NON_PROTECTED], AUTHOR, []),
    )
    assert rc == 0


# ---- workflow lint: old marker gone, new script wired in ------------------


def _workflow_text() -> str:
    return (
        ROOT_DIR / ".github" / "workflows" / "staging-self-ship-guard.yml"
    ).read_text(encoding="utf-8")


def test_workflow_no_longer_uses_ack_marker():
    assert "[constitutional-change-ack]" not in _workflow_text()


def test_workflow_calls_check_constitutional_review():
    assert "check_constitutional_review.py" in _workflow_text()


def test_workflow_grants_pull_requests_read():
    assert "pull-requests: read" in _workflow_text()
