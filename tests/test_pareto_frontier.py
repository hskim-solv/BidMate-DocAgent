"""Tests for the cost-quality Pareto frontier helper (issue #124).

PNG render goes through matplotlib which is not a CI dependency; only the
pure-Python frontier logic and the eval_summary extraction are tested here.
"""

from __future__ import annotations

import unittest

from scripts.plot_pareto import (
    ParetoPoint,
    compute_pareto_frontier,
    extract_points,
    render_markdown,
)


class TestComputeParetoFrontier(unittest.TestCase):
    def _pt(self, name: str, cost: float, quality: float) -> ParetoPoint:
        return ParetoPoint(name=name, cost=cost, quality=quality, extras={})

    def test_dominated_point_removed(self) -> None:
        # B dominates A (cheaper and higher quality) → A is dropped.
        points = [
            self._pt("A", cost=10, quality=0.5),
            self._pt("B", cost=5, quality=0.6),
        ]
        frontier = compute_pareto_frontier(points)
        self.assertEqual({p.name for p in frontier}, {"B"})

    def test_undominated_points_kept(self) -> None:
        # A is cheap-but-low-quality; B is expensive-but-high-quality.
        # Neither dominates the other.
        points = [
            self._pt("cheap_low", cost=1, quality=0.4),
            self._pt("medium", cost=5, quality=0.6),
            self._pt("expensive_high", cost=10, quality=0.9),
        ]
        frontier = compute_pareto_frontier(points)
        self.assertEqual(
            {p.name for p in frontier},
            {"cheap_low", "medium", "expensive_high"},
        )

    def test_strictly_dominated_in_middle(self) -> None:
        # `middle` is dominated by `good` (cheaper AND higher quality).
        points = [
            self._pt("cheap", cost=1, quality=0.3),
            self._pt("middle", cost=5, quality=0.5),
            self._pt("good", cost=4, quality=0.6),
            self._pt("expensive", cost=10, quality=0.9),
        ]
        frontier = compute_pareto_frontier(points)
        self.assertEqual(
            {p.name for p in frontier},
            {"cheap", "good", "expensive"},
        )

    def test_ties_are_kept(self) -> None:
        # Two points with identical cost and quality should both stay —
        # neither strictly dominates the other.
        points = [
            self._pt("twin_a", cost=5, quality=0.7),
            self._pt("twin_b", cost=5, quality=0.7),
        ]
        frontier = compute_pareto_frontier(points)
        self.assertEqual({p.name for p in frontier}, {"twin_a", "twin_b"})

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(compute_pareto_frontier([]), [])

    def test_single_point_always_on_frontier(self) -> None:
        only = self._pt("solo", cost=3, quality=0.5)
        self.assertEqual(compute_pareto_frontier([only]), [only])


class TestExtractPoints(unittest.TestCase):
    def test_run_without_required_fields_dropped(self) -> None:
        summary = {
            "ablation": {
                "runs": [
                    {"name": "ok", "latency": {"p95": 2.0}, "citation_precision": 0.9},
                    {"name": "missing_latency", "citation_precision": 0.9},
                    {"name": "missing_citation", "latency": {"p95": 5.0}},
                    {"name": "", "latency": {"p95": 1.0}, "citation_precision": 0.5},
                ]
            }
        }
        points = extract_points(summary)
        self.assertEqual([p.name for p in points], ["ok"])
        self.assertEqual(points[0].cost, 2.0)
        self.assertEqual(points[0].quality, 0.9)

    def test_citation_precision_as_dict(self) -> None:
        # Some eval_summary entries surface metrics as {"mean": ..., "ci": ...}
        # rather than a flat float. The extractor should accept both shapes.
        summary = {
            "ablation": {
                "runs": [
                    {
                        "name": "ci_form",
                        "latency": {"p95": 3.0},
                        "citation_precision": {"mean": 0.905, "ci": [0.821, 0.976]},
                        "accuracy": 0.906,
                    }
                ]
            }
        }
        points = extract_points(summary)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].quality, 0.905)

    def test_missing_ablation_block(self) -> None:
        self.assertEqual(extract_points({}), [])
        self.assertEqual(extract_points({"ablation": {}}), [])
        self.assertEqual(extract_points({"ablation": {"runs": []}}), [])


class TestRenderMarkdown(unittest.TestCase):
    def test_frontier_marker_and_sort(self) -> None:
        points = [
            ParetoPoint("expensive", cost=10, quality=0.9, extras={"accuracy": 0.95}),
            ParetoPoint("cheap", cost=1, quality=0.4, extras={"accuracy": 0.8}),
            ParetoPoint("dominated", cost=5, quality=0.3, extras={"accuracy": 0.7}),
        ]
        frontier = [points[0], points[1]]
        out = render_markdown(points, frontier)
        # Sorted by ascending cost: cheap → dominated → expensive.
        cheap_idx = out.find("| ✓ | cheap |")
        dominated_idx = out.find("|  | dominated |")
        expensive_idx = out.find("| ✓ | expensive |")
        self.assertNotEqual(cheap_idx, -1)
        self.assertNotEqual(dominated_idx, -1)
        self.assertNotEqual(expensive_idx, -1)
        self.assertLess(cheap_idx, dominated_idx)
        self.assertLess(dominated_idx, expensive_idx)
        self.assertIn("Frontier members (2):", out)


if __name__ == "__main__":
    unittest.main()
