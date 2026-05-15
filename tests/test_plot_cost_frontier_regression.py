"""Regression tests for the cost-accuracy frontier helper (ADR 0038 / issue #798).

PNG render goes through matplotlib (not a CI dependency); only the
pure-Python frontier logic and the input extraction are tested here. Pattern
mirrors ``tests/test_pareto_frontier.py`` (the sibling latency-based plotter).
"""

from __future__ import annotations

import unittest

from scripts.plot_cost_frontier import (
    DEFAULT_ACCEPTABLE_FLOOR,
    FrontierPoint,
    compute_frontier,
    extract_external_points,
    extract_inrepo_points,
    find_accuracy_ceiling,
    find_cheapest_floor,
    find_sweet_spot,
    render_markdown,
    sum_case_cost,
)


def _pt(
    name: str,
    cost: float,
    acc: float,
    *,
    ci_lo: float | None = None,
    ci_hi: float | None = None,
    is_self_hosted: bool = True,
    backend: str | None = None,
    model: str | None = None,
) -> FrontierPoint:
    return FrontierPoint(
        name=name,
        cost_usd=cost,
        accuracy=acc,
        ci_lo=ci_lo,
        ci_hi=ci_hi,
        is_self_hosted=is_self_hosted,
        backend=backend,
        model=model,
        extras={},
    )


class TestSumCaseCost(unittest.TestCase):
    def test_all_none_returns_none(self) -> None:
        self.assertIsNone(
            sum_case_cost(
                [{"cost_estimate_usd": None}, {"cost_estimate_usd": None}]
            )
        )

    def test_mixed_sums_only_non_none(self) -> None:
        self.assertAlmostEqual(
            sum_case_cost(
                [
                    {"cost_estimate_usd": 0.01},
                    {"cost_estimate_usd": None},
                    {"cost_estimate_usd": 0.005},
                ]
            ),
            0.015,
        )

    def test_empty_returns_none(self) -> None:
        # Empty input → treated as "no cost data", same as all-None.
        self.assertIsNone(sum_case_cost([]))

    def test_invalid_cost_skipped(self) -> None:
        self.assertAlmostEqual(
            sum_case_cost(
                [
                    {"cost_estimate_usd": "not a number"},
                    {"cost_estimate_usd": 0.02},
                ]
            ),
            0.02,
        )


class TestComputeFrontier(unittest.TestCase):
    def test_dominated_point_removed(self) -> None:
        # B dominates A (cheaper AND higher accuracy) → A dropped.
        points = [_pt("A", 10.0, 0.50), _pt("B", 5.0, 0.60)]
        frontier = compute_frontier(points)
        self.assertEqual({p.name for p in frontier}, {"B"})

    def test_undominated_kept(self) -> None:
        # Three-point trade-off chain stays intact.
        points = [
            _pt("cheap_low", 0.0, 0.40),
            _pt("medium", 5.0, 0.60),
            _pt("expensive_high", 10.0, 0.90),
        ]
        frontier = compute_frontier(points)
        self.assertEqual(
            {p.name for p in frontier},
            {"cheap_low", "medium", "expensive_high"},
        )

    def test_ties_kept(self) -> None:
        # Two identical points stay together — neither strictly dominates.
        points = [_pt("twin_a", 5.0, 0.7), _pt("twin_b", 5.0, 0.7)]
        frontier = compute_frontier(points)
        self.assertEqual({p.name for p in frontier}, {"twin_a", "twin_b"})

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(compute_frontier([]), [])

    def test_self_hosted_ceiling_dominates_lower_external(self) -> None:
        # Self-hosted at x=0 with high accuracy dominates any external priced
        # above it with lower accuracy — captures the ADR 0038 "any paid
        # backend with equal-or-lower accuracy is dominated" rule.
        ceiling = _pt("naive_baseline", 0.0, 0.82)
        loser = _pt(
            "external:dumb-cheap",
            0.001,
            0.40,
            is_self_hosted=False,
            backend="ext",
            model="dumb",
        )
        frontier = compute_frontier([ceiling, loser])
        self.assertEqual({p.name for p in frontier}, {"naive_baseline"})


class TestExtractInrepoPoints(unittest.TestCase):
    def test_self_hosted_cost_is_zero(self) -> None:
        # Per ADR 0038, in-repo ablations are placed at x=0 regardless of
        # any per-case cost in the summary.
        summary = {
            "ablation": {
                "runs": [
                    {"name": "naive_baseline", "accuracy": 0.78},
                    {"name": "full", "accuracy": {"mean": 0.72}},
                ]
            }
        }
        points = extract_inrepo_points(summary)
        self.assertEqual(len(points), 2)
        for p in points:
            self.assertEqual(p.cost_usd, 0.0)
            self.assertTrue(p.is_self_hosted)

    def test_missing_accuracy_dropped(self) -> None:
        summary = {"ablation": {"runs": [{"name": "x"}]}}
        self.assertEqual(extract_inrepo_points(summary), [])

    def test_ci_band_extracted(self) -> None:
        summary = {
            "ablation": {
                "runs": [
                    {
                        "name": "naive_baseline",
                        "accuracy": 0.78,
                        "ci": {"accuracy": {"ci_lo": 0.68, "ci_hi": 0.88}},
                    }
                ]
            }
        }
        points = extract_inrepo_points(summary)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].ci_lo, 0.68)
        self.assertAlmostEqual(points[0].ci_hi, 0.88)


class TestExtractExternalPoints(unittest.TestCase):
    def test_no_case_results_excluded(self) -> None:
        # Per ADR 0038, an external run without per-case cost data is
        # excluded from the plot (nothing to put on the x-axis).
        external = {
            "backend": "langchain",
            "model": "claude-sonnet-4-6",
            "metrics": {
                "accuracy": {"mean": 0.39, "ci_lo": 0.29, "ci_hi": 0.48}
            },
        }
        self.assertEqual(extract_external_points(external), [])

    def test_with_case_results_cost(self) -> None:
        external = {
            "backend": "langchain",
            "model": "claude-sonnet-4-6",
            "metrics": {
                "accuracy": {"mean": 0.39, "ci_lo": 0.29, "ci_hi": 0.48}
            },
            "case_results": [
                {"cost_estimate_usd": 0.012},
                {"cost_estimate_usd": 0.010},
            ],
        }
        points = extract_external_points(external)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].cost_usd, 0.022)
        self.assertEqual(points[0].name, "langchain:claude-sonnet-4-6")
        self.assertFalse(points[0].is_self_hosted)
        self.assertAlmostEqual(points[0].ci_lo, 0.29)
        self.assertAlmostEqual(points[0].ci_hi, 0.48)


class TestAnchors(unittest.TestCase):
    def test_accuracy_ceiling_is_best_in_repo(self) -> None:
        in_repo = [
            _pt("naive_baseline", 0.0, 0.78),
            _pt("full", 0.0, 0.72),
            _pt("no_rerank", 0.0, 0.70),
        ]
        ceiling = find_accuracy_ceiling(in_repo)
        self.assertIsNotNone(ceiling)
        assert ceiling is not None  # for type narrowing
        self.assertEqual(ceiling.name, "naive_baseline")

    def test_sweet_spot_requires_ci_lower_above_floor(self) -> None:
        # ADR 0038 sweet spot rule: CI_lo > floor (not just mean > floor).
        # "good" qualifies (CI_lo = 0.72 > 0.70). "flaky" mean is above
        # floor but CI_lo (0.65) is below → excluded.
        external = [
            _pt(
                "good",
                1.0,
                0.80,
                ci_lo=0.72,
                ci_hi=0.88,
                is_self_hosted=False,
                backend="x",
                model="g",
            ),
            _pt(
                "flaky",
                0.5,
                0.75,
                ci_lo=0.65,
                ci_hi=0.85,
                is_self_hosted=False,
                backend="x",
                model="f",
            ),
        ]
        spot = find_sweet_spot(external, floor=DEFAULT_ACCEPTABLE_FLOOR)
        self.assertIsNotNone(spot)
        assert spot is not None
        self.assertEqual(spot.name, "good")

    def test_cheapest_floor_uses_mean(self) -> None:
        # Both clear mean > 0.70 → cheaper wins.
        external = [
            _pt(
                "expensive",
                5.0,
                0.80,
                is_self_hosted=False,
                backend="x",
                model="e",
            ),
            _pt(
                "cheap",
                1.0,
                0.75,
                is_self_hosted=False,
                backend="x",
                model="c",
            ),
        ]
        cheapest = find_cheapest_floor(external, floor=DEFAULT_ACCEPTABLE_FLOOR)
        self.assertIsNotNone(cheapest)
        assert cheapest is not None
        self.assertEqual(cheapest.name, "cheap")

    def test_no_qualifier_returns_none(self) -> None:
        # All external below floor → no sweet spot, no cheapest floor.
        external = [
            _pt(
                "bad",
                1.0,
                0.40,
                ci_lo=0.30,
                ci_hi=0.50,
                is_self_hosted=False,
                backend="x",
                model="b",
            )
        ]
        self.assertIsNone(find_sweet_spot(external))
        self.assertIsNone(find_cheapest_floor(external))


class TestRenderMarkdown(unittest.TestCase):
    def test_smoke_in_repo_only(self) -> None:
        in_repo = [
            _pt(
                "naive_baseline",
                0.0,
                0.78,
                ci_lo=0.68,
                ci_hi=0.88,
            )
        ]
        external: list[FrontierPoint] = []
        frontier = compute_frontier(in_repo + external)
        out = render_markdown(
            in_repo, external, frontier, DEFAULT_ACCEPTABLE_FLOOR
        )
        self.assertIn("ADR 0038", out)
        self.assertIn("Accuracy ceiling", out)
        self.assertIn("naive_baseline", out)
        self.assertIn("$0 (self-hosted)", out)
        # CI band rendered.
        self.assertIn("[0.680–0.880]", out)


if __name__ == "__main__":
    unittest.main()
