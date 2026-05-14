"""Regression tests for axis #2 (Agent delegation) skip-rate collector.

Pins the LOC threshold, the branch-name → issue-number join, the
plan-call ↔ issue match via the transcript record's `cwd` field, and
the unmatched-PR exclusion contract (issue #718, follow-up to PR #723).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "claude-hooks"))
import _self_review as sr


def _write_transcript(path: Path, records: list[dict]) -> None:
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _plan_record(cwd: str, ts: str = "2026-04-15T10:00:00Z") -> dict:
    return {
        "timestamp": ts,
        "sessionId": f"sess-{cwd}",
        "cwd": cwd,
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "input": {"subagent_type": "Plan"},
                }
            ]
        },
    }


class TestCollectSessionsPlanCallsByIssue(unittest.TestCase):
    def test_plan_call_grouped_by_worktree_issue_number(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            _write_transcript(
                tdir / "a.jsonl",
                [
                    _plan_record(
                        "/repo/.claude/worktrees/feat-718-plan-skip-rate"
                    ),
                    _plan_record(
                        "/repo/.claude/worktrees/feat-719-smoke-hooks"
                    ),
                ],
            )
            result = sr.collect_sessions(
                str(tdir / "*.jsonl"), "2026-04-01", "2026-06-30"
            )
        self.assertEqual(result["plan_calls_by_issue"], {718: 1, 719: 1})
        self.assertEqual(result["plan_calls_unmatched_worktree"], 0)
        self.assertEqual(result["agent_delegations"]["Plan"], 2)

    def test_plan_call_without_issue_in_cwd_goes_unmatched(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            _write_transcript(
                tdir / "a.jsonl",
                [_plan_record("/repo/.claude/worktrees/ecstatic-bose-a315c1")],
            )
            result = sr.collect_sessions(
                str(tdir / "*.jsonl"), "2026-04-01", "2026-06-30"
            )
        self.assertEqual(result["plan_calls_by_issue"], {})
        self.assertEqual(result["plan_calls_unmatched_worktree"], 1)


class TestComputeAxis2SkipRate(unittest.TestCase):
    def test_loc_threshold_excludes_small_prs(self):
        prs = [
            {"number": 100, "head": "fix/issue-100-typo", "issue": 100, "loc": 5},
            {"number": 101, "head": "feat/issue-101-big", "issue": 101, "loc": 120},
        ]
        result = sr.compute_axis_2_skip_rate(prs, {101: 1})
        self.assertEqual(result["prs_nontrivial"], 1)
        self.assertEqual(result["prs_evaluated"], 1)
        self.assertEqual(result["prs_with_zero_plan_calls"], 0)
        self.assertEqual(result["skip_rate"], 0.0)

    def test_skip_rate_counts_zero_plan_call_prs(self):
        prs = [
            {"number": 200, "head": "feat/issue-200-a", "issue": 200, "loc": 80},
            {"number": 201, "head": "feat/issue-201-b", "issue": 201, "loc": 90},
            {"number": 202, "head": "feat/issue-202-c", "issue": 202, "loc": 75},
        ]
        # 200 has a Plan call; 201 / 202 do not.
        result = sr.compute_axis_2_skip_rate(prs, {200: 3})
        self.assertEqual(result["prs_evaluated"], 3)
        self.assertEqual(result["prs_with_zero_plan_calls"], 2)
        self.assertAlmostEqual(result["skip_rate"], 2 / 3)

    def test_unmatched_branch_excluded_from_denominator(self):
        prs = [
            {"number": 300, "head": "main-hotfix-no-issue", "issue": None, "loc": 100},
            {"number": 301, "head": "feat/issue-301-x", "issue": 301, "loc": 100},
        ]
        result = sr.compute_axis_2_skip_rate(prs, {301: 1})
        self.assertEqual(result["prs_nontrivial"], 2)
        self.assertEqual(result["prs_evaluated"], 1)
        self.assertEqual(result["prs_unmatched_branch"], 1)
        self.assertEqual(result["skip_rate"], 0.0)

    def test_none_rate_when_no_evaluable_prs(self):
        result = sr.compute_axis_2_skip_rate([], {})
        self.assertIsNone(result["skip_rate"])
        self.assertEqual(result["prs_evaluated"], 0)


class TestCollectPrDiffStatsParsing(unittest.TestCase):
    def test_parses_gh_json_into_loc_and_issue_fields(self):
        gh_output = json.dumps([
            {
                "number": 718,
                "headRefName": "feat/issue-718-plan-skip-rate",
                "additions": 90,
                "deletions": 10,
                "mergedAt": "2026-05-14T12:00:00Z",
            },
            {
                "number": 901,
                "headRefName": "main-revert",
                "additions": 5,
                "deletions": 5,
                "mergedAt": "2026-05-14T12:30:00Z",
            },
        ])

        class FakeProc:
            returncode = 0
            stdout = gh_output

        original_run = sr.subprocess.run
        sr.subprocess.run = lambda *a, **kw: FakeProc()  # type: ignore[assignment]
        try:
            result = sr.collect_pr_diff_stats("/repo", "2026-04-01", "2026-06-30")
        finally:
            sr.subprocess.run = original_run

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["number"], 718)
        self.assertEqual(result[0]["issue"], 718)
        self.assertEqual(result[0]["loc"], 100)
        self.assertIsNone(result[1]["issue"])


if __name__ == "__main__":
    unittest.main()
