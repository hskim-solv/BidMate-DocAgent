"""Tests for scripts/claude-hooks/_ship_lock_check.py.

Drives the multi-agent owner map directly (owner_of) and exercises the
CLI _check() with parameterised (branch, files) tuples to catch
regressions in the ownership table or the bypass envvar handling.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
sys.path.insert(0, str(ROOT_DIR / "scripts" / "claude-hooks"))

import _ship_lock_check as lc  # noqa: E402


@pytest.mark.parametrize("path,expected_owner", [
    ("rag_core.py", 238),
    ("./rag_core.py", 238),
    ("ingestion.py", 239),
    ("visual_ingestion.py", 239),
    ("rag_normalize.py", 239),
    ("rag_synthesis.py", 240),
    ("eval/config.yaml", 241),
    ("eval/run_eval.py", 241),
    ("scripts/leaderboard.py", 241),
    ("rag_observability.py", 242),
    ("api/main.py", 243),
    ("app.py", 243),
    ("demo/streamlit_app.py", 243),
    (".github/workflows/pr-eval.yml", 244),
    (".githooks/pre-commit", 244),
    (".github/pull_request_template.md", 244),
    (".claude/settings.json", 244),
    ("README.md", None),  # unowned
    ("docs/multi-agent-ownership.md", None),
    ("scripts/check_branch_and_issue.py", 244),
    ("tests/test_governance.py", None),
])
def test_owner_of(path, expected_owner):
    assert lc.owner_of(path) == expected_owner


def test_owner_of_empty():
    assert lc.owner_of("") is None
    assert lc.owner_of("./") is None or lc.owner_of("./") == lc.owner_of("")


def test_check_branch_owns_files():
    rc = lc._check("feat/issue-238-pipeline-tweak", ["rag_core.py", "tests/test_x.py"])
    assert rc == 0


def test_check_unowned_files_only():
    rc = lc._check("feat/issue-200-docs", ["README.md", "docs/foo.md"])
    assert rc == 0


def test_check_cross_owner_violation(capsys):
    rc = lc._check("feat/issue-200-foo", ["rag_core.py"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ship-lock" in err
    assert "#238" in err
    assert "#200" in err or "200" in err


def test_check_cross_owner_bypass(monkeypatch, capsys):
    monkeypatch.setenv("CROSS_OWNER", "ack")
    rc = lc._check("feat/issue-200-foo", ["rag_core.py"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "acknowledged" in err.lower() or "ack" in err.lower()


def test_check_branch_violates_adr_0007(capsys):
    rc = lc._check("not-a-valid-branch", ["rag_core.py"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ADR 0007" in err or "violates" in err.lower()


def test_check_exempt_branch_skips():
    rc = lc._check("dependabot/npm/foo-1.2.3", ["rag_core.py"])
    assert rc == 0


def test_owner_map_has_no_orphan_root_files():
    """Every owned root file mentioned in OWNER_MAP exists in repo or is
    under a directory entry — guards against typos drifting silently."""
    skipped_dirs = [k for k in lc.OWNER_MAP if k.endswith("/")]
    file_entries = [k for k in lc.OWNER_MAP if not k.endswith("/")]
    for entry in file_entries:
        if any(entry.startswith(d) for d in skipped_dirs):
            continue
        assert (ROOT_DIR / entry).exists(), (
            f"OWNER_MAP entry {entry!r} not found on disk — typo?"
        )
