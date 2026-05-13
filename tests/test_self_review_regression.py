"""Regression tests for governance hook fire log collector (issue #502).

Pins backward-compatible log parsing, action distribution split,
quarter-window filtering, ADR proposed→accepted lag calculation, and
that unaccepted ADRs are not emitted.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "claude-hooks"))
import _self_review as sr


class TestHookFiresBackwardCompat(unittest.TestCase):
    def test_legacy_2field_and_4field_both_counted(self):
        lines = (
            "2026-04-01T10:00:00Z|rag_core.py\n"
            "2026-04-02T11:00:00Z|aware|load-bearing|rag_retrieval.py\n"
            "2025-12-01T00:00:00Z|aware|load-bearing|old.py\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["pretooluse_loadbearing_fires"], 2)
        self.assertIn("aware", result["fires_by_action"])


class TestHookFiresActionDistribution(unittest.TestCase):
    def test_aware_and_blocked_counted_separately(self):
        lines = (
            "2026-04-01T10:00:00Z|aware|load-bearing|rag_core.py\n"
            "2026-04-02T10:00:00Z|blocked|gh-merge-delete-branch|feat/issue-99\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["fires_by_action"].get("aware"), 1)
        self.assertEqual(result["fires_by_action"].get("blocked"), 1)
        self.assertEqual(result["pretooluse_loadbearing_fires"], 2)


class TestHookFiresQuarterWindowFilter(unittest.TestCase):
    def test_outside_window_excluded(self):
        lines = (
            "2025-12-31T23:59:59Z|aware|load-bearing|old.py\n"
            "2026-07-01T00:00:00Z|aware|load-bearing|future.py\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["pretooluse_loadbearing_fires"], 0)


def _git(*args, cwd, **kwargs):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, **kwargs)


def _make_repo_with_adr(
    td: str,
    adr_filename: str,
    content_at_add: str,
    content_at_accept: str | None,
    add_date: str,
    accept_date: str | None,
) -> Path:
    repo = Path(td)
    adr_dir = repo / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    adr_path = adr_dir / adr_filename
    _git("init", cwd=str(repo))
    _git("config", "user.email", "test@test.com", cwd=str(repo))
    _git("config", "user.name", "Test", cwd=str(repo))
    adr_path.write_text(content_at_add)
    _git("add", ".", cwd=str(repo))
    env = {**os.environ, "GIT_COMMITTER_DATE": add_date}
    _git("commit", f"--date={add_date}", "-m", f"add {adr_filename}", cwd=str(repo), env=env)
    if content_at_accept is not None and accept_date is not None:
        adr_path.write_text(content_at_accept)
        _git("add", ".", cwd=str(repo))
        env2 = {**os.environ, "GIT_COMMITTER_DATE": accept_date}
        _git("commit", f"--date={accept_date}", "-m", f"accept {adr_filename}", cwd=str(repo), env=env2)
    return repo


class TestRuleToAutomationLagBasic(unittest.TestCase):
    def test_lag_days_computed_correctly(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_repo_with_adr(
                td,
                "0001-test.md",
                content_at_add="- **Status**: proposed\n",
                content_at_accept="- **Status**: accepted\n",
                add_date="2026-04-01T10:00:00+00:00",
                accept_date="2026-04-11T10:00:00+00:00",
            )
            lags = sr._compute_adr_lags(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(len(lags), 1)
        self.assertEqual(lags[0]["adr_id"], "0001")
        self.assertEqual(lags[0]["lag_days"], 10)


class TestRuleToAutomationLagSkipsUnaccepted(unittest.TestCase):
    def test_proposed_only_not_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_repo_with_adr(
                td,
                "0002-unaccepted.md",
                content_at_add="- **Status**: proposed\n",
                content_at_accept=None,
                add_date="2026-04-01T10:00:00+00:00",
                accept_date=None,
            )
            lags = sr._compute_adr_lags(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(lags, [])


if __name__ == "__main__":
    unittest.main()
