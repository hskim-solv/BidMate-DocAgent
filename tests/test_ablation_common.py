"""Unit tests for ``scripts/_ablation_common`` — the mode-agnostic helpers
shared by Phase 2 (chunking ablation) and Phase 3 (mode ablation).

PR #952 (Phase 2) did not add helper-level tests; this file fills that
gap as part of the PR-C extraction (issue #953).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts._ablation_common import (  # noqa: E402
    _category_split,
    _fmt_ci,
    _seed_averaged_paired_ci,
    categories_from_case,
    compute_deltas,
)


class CategoriesFromCaseTest(unittest.TestCase):
    def test_categories_from_case_uncategorized_fallback(self) -> None:
        # Empty / missing / falsy hardcase_categories all collapse to
        # the "uncategorized" bucket so the case still appears once.
        self.assertEqual(categories_from_case({}), ["uncategorized"])
        self.assertEqual(
            categories_from_case({"hardcase_categories": []}), ["uncategorized"]
        )
        self.assertEqual(
            categories_from_case({"hardcase_categories": None}), ["uncategorized"]
        )
        # Non-empty tag list passes through untouched, stringified.
        self.assertEqual(
            categories_from_case({"hardcase_categories": ["multi_hop"]}),
            ["multi_hop"],
        )
        self.assertEqual(
            categories_from_case(
                {"hardcase_categories": ["multi_hop", "distractor_heavy"]}
            ),
            ["multi_hop", "distractor_heavy"],
        )


class CategorySplitTest(unittest.TestCase):
    def test_category_split_multi_tag_overlap(self) -> None:
        # A case tagged with two categories must contribute one row to
        # each bucket AND one row to `overall` — paired CIs of those
        # buckets share the same case, which is intentional.
        rows = [
            {"categories": ["multi_hop"], "metric_x": 0.5},
            {"categories": ["multi_hop", "distractor_heavy"], "metric_x": 0.7},
            {"categories": ["distractor_heavy"], "metric_x": 0.3},
        ]
        split = _category_split(rows, "metric_x")
        self.assertEqual(split["overall"], [0.5, 0.7, 0.3])
        self.assertEqual(split["multi_hop"], [0.5, 0.7])
        self.assertEqual(split["distractor_heavy"], [0.7, 0.3])

    def test_category_split_legacy_category_fallback(self) -> None:
        # Old raw_results.json predating the `categories` list field
        # must still re-aggregate via the single-string `category` key.
        rows = [
            {"category": "single_hop", "metric_x": 0.4},
            {"metric_x": 0.6},  # no tag at all
        ]
        split = _category_split(rows, "metric_x")
        self.assertEqual(split["overall"], [0.4, 0.6])
        self.assertEqual(split["single_hop"], [0.4])
        self.assertEqual(split["uncategorized"], [0.6])


class ComputeDeltasTest(unittest.TestCase):
    def test_compute_deltas_none_on_length_mismatch(self) -> None:
        # Different per-category sample sizes between current/other must
        # collapse to None — the runner cannot pair scores across runs
        # of different cardinality, and silently returning a fake CI
        # would violate absolute rule #2 (no fake metrics).
        current = [
            {"categories": ["multi_hop"], "m": 0.5},
            {"categories": ["multi_hop"], "m": 0.7},
        ]
        other = [
            {"categories": ["multi_hop"], "m": 0.6},
            # missing second row → mismatch for multi_hop bucket
        ]
        deltas = compute_deltas(current, other, "m", seeds=[17])
        self.assertIsNone(deltas["multi_hop"])
        # overall also mismatches (length 2 vs 1)
        self.assertIsNone(deltas["overall"])


class SeedAveragedPairedCITest(unittest.TestCase):
    def test_seed_averaged_paired_ci_seeds_echoed(self) -> None:
        # Multiple seeds → averaged statistics but seed-invariant `n`
        # and an echo of the seed list so downstream consumers can
        # reconstruct provenance from the dict alone.
        a = [0.5, 0.7, 0.6, 0.8]
        b = [0.4, 0.6, 0.5, 0.7]
        seeds = [17, 23, 29]
        result = _seed_averaged_paired_ci(a, b, seeds)
        self.assertIsNotNone(result)
        assert result is not None  # mypy
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["seeds"], [17, 23, 29])
        self.assertIn("mean_diff", result)
        self.assertIn("ci_lo", result)
        self.assertIn("ci_hi", result)
        # mean_diff should be close to actual mean diff (0.1) since
        # paired bootstrap is unbiased for the mean.
        self.assertAlmostEqual(float(result["mean_diff"]), 0.1, places=2)


class FmtCiTest(unittest.TestCase):
    def test_fmt_ci_significance_boundary(self) -> None:
        # CI that straddles 0 → NOT SIGNIFICANT.
        ci_straddle = {"mean_diff": 0.0, "ci_lo": -0.001, "ci_hi": 0.001}
        self.assertIn("NOT SIGNIFICANT", _fmt_ci(ci_straddle))
        # CI strictly above 0 → significant.
        ci_above = {"mean_diff": 0.003, "ci_lo": 0.001, "ci_hi": 0.005}
        out_above = _fmt_ci(ci_above)
        self.assertIn("significant", out_above)
        self.assertNotIn("NOT SIGNIFICANT", out_above)
        # CI strictly below 0 → significant.
        ci_below = {"mean_diff": -0.003, "ci_lo": -0.005, "ci_hi": -0.001}
        out_below = _fmt_ci(ci_below)
        self.assertIn("significant", out_below)
        self.assertNotIn("NOT SIGNIFICANT", out_below)
        # None → "N/A" so caller never sees a fabricated band.
        self.assertEqual(_fmt_ci(None), "N/A")


if __name__ == "__main__":
    unittest.main()
