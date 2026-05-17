"""Contract tests for the bootstrap CI utility.

The estimator is seeded by ``numpy.random.default_rng`` so two runs over
the same case results produce byte-identical CI output across platforms.
Without that determinism, ``scripts/update_readme_metrics.py --check``
would fail intermittently in CI.

These tests also lock the basic statistical properties: CI brackets the
sample mean, width shrinks with n, the bands hit (0, 1) bounds correctly
on degenerate inputs, and the seed is honored.
"""

from __future__ import annotations

import unittest

from eval.bootstrap import (
    DEFAULT_NUM_RESAMPLES,
    bootstrap_ci,
    format_ci_band,
    paired_bootstrap_ci,
)


class BootstrapCITest(unittest.TestCase):
    def test_returns_none_on_empty(self) -> None:
        self.assertIsNone(bootstrap_ci([]))

    def test_mean_matches_arithmetic_mean(self) -> None:
        values = [1.0, 0.0, 1.0, 1.0, 0.0]
        ci = bootstrap_ci(values)
        self.assertIsNotNone(ci)
        assert ci is not None
        self.assertAlmostEqual(ci["mean"], 0.6, places=10)
        self.assertEqual(ci["n"], 5)
        self.assertEqual(ci["num_resamples"], DEFAULT_NUM_RESAMPLES)
        self.assertEqual(ci["alpha"], 0.05)

    def test_ci_brackets_mean(self) -> None:
        values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
        ci = bootstrap_ci(values)
        assert ci is not None
        self.assertLessEqual(ci["ci_lo"], ci["mean"])
        self.assertGreaterEqual(ci["ci_hi"], ci["mean"])

    def test_degenerate_uniform_values_have_zero_width(self) -> None:
        ci = bootstrap_ci([1.0, 1.0, 1.0, 1.0])
        assert ci is not None
        self.assertEqual(ci["mean"], 1.0)
        self.assertEqual(ci["ci_lo"], 1.0)
        self.assertEqual(ci["ci_hi"], 1.0)

    def test_seed_is_deterministic(self) -> None:
        values = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0]
        ci_a = bootstrap_ci(values, seed=17)
        ci_b = bootstrap_ci(values, seed=17)
        self.assertEqual(ci_a, ci_b)

    def test_seed_independence_of_mean(self) -> None:
        # The point estimate is the sample mean — independent of the
        # bootstrap seed. Only the CI bounds depend on resampling.
        values = [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4, 0.6, 0.8, 0.55]
        ci_17 = bootstrap_ci(values, seed=17)
        ci_42 = bootstrap_ci(values, seed=42)
        assert ci_17 is not None and ci_42 is not None
        self.assertEqual(ci_17["mean"], ci_42["mean"])
        self.assertEqual(ci_17["n"], ci_42["n"])

    def test_ci_width_shrinks_with_n(self) -> None:
        # A 50/50 binary sample's CI half-width should narrow as n grows.
        # 1000 resamples is fixed so the only changing input is sample
        # size — this locks the n-scaling property of the estimator.
        small = bootstrap_ci([1.0, 0.0] * 5, seed=17)
        large = bootstrap_ci([1.0, 0.0] * 50, seed=17)
        assert small is not None and large is not None
        small_width = small["ci_hi"] - small["ci_lo"]
        large_width = large["ci_hi"] - large["ci_lo"]
        self.assertGreater(small_width, large_width)

    def test_bounds_stay_inside_zero_one_for_bounded_metric(self) -> None:
        ci = bootstrap_ci([1.0, 1.0, 1.0, 1.0, 0.0])
        assert ci is not None
        self.assertGreaterEqual(ci["ci_lo"], 0.0)
        self.assertLessEqual(ci["ci_hi"], 1.0)

    def test_format_ci_band_renders_full_band(self) -> None:
        ci = {"mean": 0.906, "ci_lo": 0.781, "ci_hi": 1.000}
        self.assertEqual(format_ci_band(ci, digits=3), "0.906 (0.781–1.000)")

    def test_format_ci_band_handles_none(self) -> None:
        self.assertEqual(format_ci_band(None), "N/A")
        self.assertEqual(format_ci_band({"mean": None}), "N/A")


class PairedBootstrapCITest(unittest.TestCase):
    def test_paired_bootstrap_ci_deterministic_seed(self) -> None:
        a = [1.0, 0.0, 1.0, 0.0, 1.0]
        b = [0.0, 1.0, 1.0, 0.0, 1.0]
        ci_1 = paired_bootstrap_ci(a, b, seed=17)
        ci_2 = paired_bootstrap_ci(a, b, seed=17)
        self.assertEqual(ci_1, ci_2)

    def test_paired_bootstrap_ci_zero_diff_when_identical(self) -> None:
        # Identical per-case scores → every paired resample sees 0 → CI collapses.
        values = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
        ci = paired_bootstrap_ci(values, list(values), seed=17)
        assert ci is not None
        self.assertEqual(ci["mean_diff"], 0.0)
        self.assertEqual(ci["ci_lo"], 0.0)
        self.assertEqual(ci["ci_hi"], 0.0)

    def test_paired_ci_brackets_mean_diff(self) -> None:
        a = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
        b = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
        ci = paired_bootstrap_ci(a, b, seed=17)
        assert ci is not None
        self.assertLessEqual(ci["ci_lo"], ci["mean_diff"])
        self.assertGreaterEqual(ci["ci_hi"], ci["mean_diff"])
        self.assertEqual(ci["n"], 8)
        self.assertEqual(ci["num_resamples"], DEFAULT_NUM_RESAMPLES)

    def test_paired_bootstrap_ci_invalid_inputs(self) -> None:
        self.assertIsNone(paired_bootstrap_ci([], []))
        self.assertIsNone(paired_bootstrap_ci([1.0], []))
        self.assertIsNone(paired_bootstrap_ci([], [1.0]))
        self.assertIsNone(paired_bootstrap_ci([1.0, 2.0], [1.0]))
        ci = paired_bootstrap_ci([1.0], [2.0], seed=17)
        assert ci is not None
        self.assertEqual(ci["mean_diff"], -1.0)
        self.assertEqual(ci["n"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
