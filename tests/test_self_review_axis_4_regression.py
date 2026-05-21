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

    def test_zero_lag_count_from_zero_lag_flag(self) -> None:
        lags = [
            {"adr_id": "0040", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0041", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0042", "lag_days": 5, "zero_lag": False},
        ]
        result = sr.compute_adr_lag_summary(lags)
        self.assertEqual(result["zero_lag_count"], 2)
        # zero_lag flag must not perturb the existing lag aggregation
        self.assertEqual(result["count"], 3)
        # the misleading is_retrofit name (#1067) is gone (#1147)
        self.assertNotIn("retrofit_count", result)

    def test_zero_lag_count_absent_flag_counts_zero(self) -> None:
        # Defensive: entries without zero_lag (e.g. older callers) must
        # not raise and contribute 0 to the zero-lag count.
        lags = [{"adr_id": "0040", "lag_days": 3}]
        result = sr.compute_adr_lag_summary(lags)
        self.assertEqual(result["zero_lag_count"], 0)

    def test_non_zero_lag_excludes_zero_lag_entries(self) -> None:
        # Issue #1147: #4-A must grade on a zero-lag-excluded mean so a
        # quarter padded with same-day ADRs cannot flatten the lag toward 0.
        lags = [
            {"adr_id": "0040", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0041", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0042", "lag_days": 6, "zero_lag": False},
            {"adr_id": "0043", "lag_days": 12, "zero_lag": False},
        ]
        result = sr.compute_adr_lag_summary(lags)
        # full mean is dragged down by the two zero-lag ADRs ...
        self.assertAlmostEqual(result["mean"], 4.5)
        # ... but the grading input excludes them.
        self.assertEqual(result["non_zero_lag"]["count"], 2)
        self.assertAlmostEqual(result["non_zero_lag"]["mean"], 9.0)
        self.assertEqual(result["zero_lag_count"], 2)

    def test_all_zero_lag_non_zero_summary_is_empty_skeleton(self) -> None:
        # When every ADR is zero-lag the lag signal is unmeasurable; the
        # non_zero_lag summary must be an empty skeleton (mean=None) so the
        # rubric flags 측정 부재 rather than reading a flattering mean=0.
        lags = [
            {"adr_id": "0040", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0041", "lag_days": 0, "zero_lag": True},
        ]
        result = sr.compute_adr_lag_summary(lags)
        self.assertEqual(result["zero_lag_count"], 2)
        self.assertEqual(result["non_zero_lag"]["count"], 0)
        self.assertIsNone(result["non_zero_lag"]["mean"])


class TestEmitReportSurfacesZeroLag(unittest.TestCase):
    """Issue #1147: the zero-lag count + non-zero mean must reach the
    Markdown summary the LLM grader reads — not stay buried in raw JSON."""

    def _minimal_stats(self, adr_lags: list[dict]) -> dict:
        return {
            "quarter": "Q2-2026",
            "date_range": ["2026-04-01", "2026-06-30"],
            "sessions": {"count": 0},
            "memory": {},
            "git": {
                "commits": 0, "load_bearing_touches": 0,
                "adr_changes": [], "prs_merged": [],
            },
            "governance_hooks": {"memory_lines": {"aware": 0, "blocked": 0}},
            "pr_diff_stats": [],
            "axis_2_plan_subagent_skip_rate": {
                "skip_rate": None, "prs_with_zero_plan_calls": 0,
                "prs_evaluated": 0,
            },
            "axis_4_cycle_time": {
                "adr_lag_days": sr.compute_adr_lag_summary(adr_lags),
                "pr_turnaround_hours": sr.compute_pr_turnaround_summary([]),
            },
            "axis_5_memory_hygiene": {
                "content_freshness": {
                    "fresh_rate": None, "fresh_in_quarter": 0, "total": 0,
                },
            },
        }

    def test_zero_lag_and_non_zero_mean_in_markdown(self) -> None:
        lags = [
            {"adr_id": "0040", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0041", "lag_days": 0, "zero_lag": True},
            {"adr_id": "0042", "lag_days": 6, "zero_lag": False},
        ]
        report = sr.emit_report(self._minimal_stats(lags))
        adr_line = next(
            ln for ln in report.splitlines() if "Axis #4 ADR lag" in ln
        )
        # the grader-visible summary line carries both new signals
        self.assertIn("zero-lag=2", adr_line)
        self.assertIn("non-zero mean=6.0", adr_line)


if __name__ == "__main__":
    unittest.main()
