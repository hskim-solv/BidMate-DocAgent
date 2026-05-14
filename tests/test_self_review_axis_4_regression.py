"""Regression tests for axis #4 (사이클 타임) cycle-time signals.

Pins the n-sample summary helper, the gh-ISO timestamp parser (handles
the trailing `Z` UTC suffix), the PR turnaround aggregator (which reuses
`collect_pr_diff_stats` output instead of issuing a second `gh` call),
and the ADR lag summary aggregator. Issue #724, follow-up to PR #723.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "claude-hooks"))
import _self_review as sr


class TestSummaryHelper(unittest.TestCase):
    def test_empty_input_returns_nones(self) -> None:
        result = sr._summary_p50_p90([])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["mean"])
        self.assertIsNone(result["p50"])
        self.assertIsNone(result["p90"])

    def test_five_sample_mean_and_percentiles(self) -> None:
        result = sr._summary_p50_p90([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["mean"], 3.0)
        self.assertEqual(result["p50"], 3.0)
        # int(5 * 0.9) = 4 → sv[4] = 5.0 (intentionally collapses to max
        # for small n; doc-string pins this conservative behaviour).
        self.assertEqual(result["p90"], 5.0)

    def test_unsorted_input_is_sorted_internally(self) -> None:
        result = sr._summary_p50_p90([10.0, 1.0, 5.0])
        self.assertEqual(result["p50"], 5.0)


class TestGhIsoParser(unittest.TestCase):
    def test_z_suffix_parsed_to_aware_utc(self) -> None:
        dt = sr._parse_gh_iso("2026-04-15T10:00:00Z")
        self.assertIsNotNone(dt)
        self.assertIsNotNone(dt.tzinfo)

    def test_invalid_input_returns_none(self) -> None:
        self.assertIsNone(sr._parse_gh_iso(None))
        self.assertIsNone(sr._parse_gh_iso(""))
        self.assertIsNone(sr._parse_gh_iso("not-a-timestamp"))


class TestComputePrTurnaroundSummary(unittest.TestCase):
    def test_hours_between_created_and_merged(self) -> None:
        prs = [
            {
                "number": 1,
                "created_at": "2026-04-15T10:00:00Z",
                "merged_at": "2026-04-15T14:00:00Z",   # +4h
            },
            {
                "number": 2,
                "created_at": "2026-04-16T10:00:00Z",
                "merged_at": "2026-04-17T10:00:00Z",   # +24h
            },
        ]
        result = sr.compute_pr_turnaround_summary(prs)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["mean"], 14.0)
        self.assertEqual(result["min"], 4.0)
        self.assertEqual(result["max"], 24.0)

    def test_missing_timestamps_are_dropped(self) -> None:
        prs = [
            {"number": 3, "created_at": None, "merged_at": "2026-04-15T10:00:00Z"},
            {"number": 4, "created_at": "2026-04-15T10:00:00Z", "merged_at": None},
        ]
        result = sr.compute_pr_turnaround_summary(prs)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["mean"])

    def test_empty_pr_list_returns_summary_skeleton(self) -> None:
        result = sr.compute_pr_turnaround_summary([])
        self.assertEqual(result["count"], 0)
        self.assertNotIn("min", result)


class TestComputeAdrLagSummary(unittest.TestCase):
    def test_aggregates_lag_days_field(self) -> None:
        lags = [
            {"adr_id": "0040", "lag_days": 1},
            {"adr_id": "0041", "lag_days": 3},
            {"adr_id": "0042", "lag_days": 8},
        ]
        result = sr.compute_adr_lag_summary(lags)
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["mean"], 4.0)

    def test_missing_lag_days_excluded(self) -> None:
        lags = [{"adr_id": "0099", "proposed_date": "2026-04-01"}]
        result = sr.compute_adr_lag_summary(lags)
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
