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
from unittest import mock

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


class TestHookFiresV2FiveField(unittest.TestCase):
    """Issue #1196: v2 5-field lines (ADR 0060) must parse with clean
    fires_by_path keys. The old ad-hoc ``split("|", 3)`` fused
    ``<category>|<path>`` into the path token, so every v2 fire produced a
    corrupted key (e.g. ``"file-edit|rag_core.py"``)."""

    def test_v2_5field_fires_by_path_is_clean(self):
        lines = (
            "2026-04-01T10:00:00Z|aware|loadbearing|file-edit|rag_core.py\n"
            "2026-04-02T10:00:00Z|nudged|delegation-gate|agent-delegation|<user-prompt>\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        # path is the 5th field only — NOT "<category>|<path>".
        self.assertEqual(
            result["fires_by_path"], {"rag_core.py": 1, "<user-prompt>": 1}
        )
        self.assertNotIn("file-edit|rag_core.py", result["fires_by_path"])
        # outcome (field 2), not the buggy hook field, drives the action split.
        self.assertEqual(result["fires_by_action"].get("aware"), 1)
        self.assertEqual(result["fires_by_action"].get("nudged"), 1)
        self.assertEqual(result["pretooluse_loadbearing_fires"], 2)

    def test_v2_5field_memory_lines_matched_by_hook(self):
        # memory-lines fires are matched on the parsed hook field, not on a
        # category that happens to equal "memory-lines". In v2 the real
        # category is "line-count"; the hook field carries "memory-lines".
        lines = (
            "2026-04-01T10:00:00Z|aware|memory-lines|line-count|MEMORY.md\n"
            "2026-04-01T11:00:00Z|aware|memory-lines|line-count|MEMORY.md\n"
            "2026-04-01T12:00:00Z|blocked|memory-lines|line-count|MEMORY.md\n"
            "2026-04-01T13:00:00Z|aware|loadbearing|file-edit|rag_core.py\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["memory_lines"], {"aware": 2, "blocked": 1})
        # the v2 memory-lines path key is clean (MEMORY.md, not line-count|MEMORY.md).
        self.assertIn("MEMORY.md", result["fires_by_path"])
        self.assertNotIn("line-count|MEMORY.md", result["fires_by_path"])

    def test_mixed_2field_4field_5field_all_parse(self):
        # 2-field (pre-0060 shim) + 4-field (legacy) + 5-field (v2) all count,
        # each with a clean path key.
        lines = (
            "2026-04-01T10:00:00Z|legacy2.py\n"
            "2026-04-01T11:00:00Z|aware|load-bearing|legacy4.py\n"
            "2026-04-01T12:00:00Z|aware|loadbearing|file-edit|v2.py\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["pretooluse_loadbearing_fires"], 3)
        self.assertEqual(
            set(result["fires_by_path"]), {"legacy2.py", "legacy4.py", "v2.py"}
        )

    def test_v2_5field_with_trailing_extra_field(self):
        # bash-guard emits a 6th `extra` field; path must still be field 5.
        lines = (
            "2026-04-01T10:00:00Z|blocked|bash-guard|gh-pr-create-stacked|"
            "feat/issue-99-foo|on=feat/issue-88-bar\n"
        )
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".claude").mkdir()
            (repo / ".claude" / ".hook-fires.log").write_text(lines)
            result = sr.collect_governance_hooks(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(result["fires_by_path"], {"feat/issue-99-foo": 1})
        self.assertEqual(result["fires_by_action"].get("blocked"), 1)


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
        # zero_lag must be present and False for a genuine multi-day lag.
        self.assertIn("zero_lag", lags[0])
        self.assertFalse(lags[0]["zero_lag"])
        # the misleading is_retrofit name (#1067) is gone (#1147).
        self.assertNotIn("is_retrofit", lags[0])


class TestSameDayAdrIsZeroLagNotRetrofit(unittest.TestCase):
    def test_genuine_same_day_decision_is_zero_lag_not_retrofit(self):
        # Issue #1147: a real same-day proposed→accepted decision yields
        # lag_days == 0. It must be labeled honestly as zero_lag (a fact),
        # NOT silently asserted to be a retrofit. The is_retrofit field from
        # #1067 is gone; grading runs on non_zero_lag so this fast decision
        # is neither mislabeled nor penalized.
        with tempfile.TemporaryDirectory() as td:
            repo = _make_repo_with_adr(
                td,
                "0003-same-day.md",
                content_at_add="- **Status**: proposed\n",
                content_at_accept="- **Status**: accepted\n",
                add_date="2026-04-05T09:00:00+00:00",
                accept_date="2026-04-05T15:00:00+00:00",
            )
            lags = sr._compute_adr_lags(str(repo), "2026-04-01", "2026-06-30")
        self.assertEqual(len(lags), 1)
        self.assertEqual(lags[0]["lag_days"], 0)
        self.assertTrue(lags[0]["zero_lag"])
        self.assertNotIn("is_retrofit", lags[0])
        # excluded from the grading mean rather than dragging it toward 0
        summary = sr.compute_adr_lag_summary(lags)
        self.assertEqual(summary["zero_lag_count"], 1)
        self.assertEqual(summary["non_zero_lag"]["count"], 0)


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


class TestComputeAdrLagsHandlesZSuffix(unittest.TestCase):
    def test_z_suffixed_git_timestamps_are_parsed(self):
        # Issue #1185: git `%aI` emits a `Z` UTC suffix. `_compute_adr_lags`
        # must parse it on every supported interpreter (3.9+), but raw
        # `datetime.fromisoformat("...Z")` raises ValueError on Python ≤3.10 —
        # which the function's `except` swallows, silently emptying the entire
        # axis-4 ADR-lag signal. We mock the two `git log` subprocess calls so
        # the test is deterministic regardless of the local git's actual
        # timestamp format or the interpreter version: before the fix this
        # asserted len 0 on ≤3.10; after the fix it parses on all Pythons.
        with tempfile.TemporaryDirectory() as td:
            adr_dir = Path(td) / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "0001-z.md").write_text("- **Status**: accepted\n")

            proposed = mock.Mock(stdout="2026-04-01T10:00:00Z\n")
            accepted = mock.Mock(stdout="2026-04-09T10:00:00Z\n")
            with mock.patch.object(
                sr.subprocess, "run", side_effect=[proposed, accepted]
            ):
                lags = sr._compute_adr_lags(td, "2026-04-01", "2026-06-30")

        self.assertEqual(len(lags), 1)
        self.assertEqual(lags[0]["adr_id"], "0001")
        self.assertEqual(lags[0]["lag_days"], 8)


if __name__ == "__main__":
    unittest.main()
