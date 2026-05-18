"""Phase 5 audit item 2 supply — failure_distribution renderer regression guard.

Verifies the renderer's output schema + percentage math + ADR 0059
first-match-wins contract surfacing. Stub eval_summary.json inputs only
— no real-eval dependency.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.render_failure_distribution import (
    SAFE_CATEGORIES,
    SAFE_OUTCOME_KEYS,
    build_aggregate,
    main,
    render_markdown,
)


def _summary(
    *,
    num_predictions: int = 221,
    counts: dict[str, int] | None = None,
    outcomes: dict[str, int] | None = None,
) -> dict[str, object]:
    """Build a minimal eval_summary.json-shaped dict.

    Only the top-level keys the renderer reads are populated;
    fixtures stay small enough that schema drift surfaces as a test
    failure rather than silently passing.
    """
    return {
        "num_predictions": num_predictions,
        "failure_category_counts": counts or {category: 0 for category in SAFE_CATEGORIES},
        "abstention_outcomes": outcomes or {key: 0 for key in SAFE_OUTCOME_KEYS},
    }


class TestBuildAggregateSchema(unittest.TestCase):
    """Aggregate JSON always has the same shape, with all 7 categories."""

    def test_all_seven_categories_present(self) -> None:
        agg = build_aggregate(_summary(counts={"retrieval_miss": 50}))
        self.assertEqual(set(agg["failure_category_counts"].keys()), set(SAFE_CATEGORIES))
        self.assertEqual(
            set(agg["failure_category_percent_of_failed"].keys()), set(SAFE_CATEGORIES)
        )
        self.assertEqual(set(agg["abstention_outcomes"].keys()), set(SAFE_OUTCOME_KEYS))
        self.assertIn("finding_1_contract", agg)
        self.assertEqual(agg["schema_version"], 1)

    def test_percentage_math(self) -> None:
        # 60 retrieval_miss + 40 verifier_false_negative = 100 failures.
        # retrieval_miss = 60% of failures, verifier_false_negative = 40%.
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = 60
        counts["verifier_false_negative"] = 40
        agg = build_aggregate(_summary(num_predictions=221, counts=counts))
        self.assertEqual(agg["total_failures"], 100)
        self.assertEqual(agg["failure_category_percent_of_failed"]["retrieval_miss"], 60.0)
        self.assertEqual(
            agg["failure_category_percent_of_failed"]["verifier_false_negative"], 40.0
        )
        # Empty categories report 0.0%, not absent.
        self.assertEqual(agg["failure_category_percent_of_failed"]["unknown"], 0.0)

    def test_zero_failures_does_not_div_by_zero(self) -> None:
        agg = build_aggregate(_summary(num_predictions=221))
        self.assertEqual(agg["total_failures"], 0)
        for category in SAFE_CATEGORIES:
            self.assertEqual(agg["failure_category_percent_of_failed"][category], 0.0)


class TestFinding1Contract(unittest.TestCase):
    """ADR 0059 — verifier_false_negative MUST equal incorrect_answer."""

    def test_contract_match_reports_true(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["verifier_false_negative"] = 65
        outcomes = {key: 0 for key in SAFE_OUTCOME_KEYS}
        outcomes["incorrect_answer"] = 65
        agg = build_aggregate(_summary(counts=counts, outcomes=outcomes))
        self.assertTrue(agg["finding_1_contract"]["match"])
        self.assertEqual(agg["finding_1_contract"]["verifier_false_negative"], 65)
        self.assertEqual(agg["finding_1_contract"]["incorrect_answer"], 65)

    def test_contract_mismatch_reports_false(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["verifier_false_negative"] = 60  # bug: != incorrect_answer
        outcomes = {key: 0 for key in SAFE_OUTCOME_KEYS}
        outcomes["incorrect_answer"] = 65
        agg = build_aggregate(_summary(counts=counts, outcomes=outcomes))
        self.assertFalse(agg["finding_1_contract"]["match"])


class TestSchemaDriftDefence(unittest.TestCase):
    """Unknown keys in failure_category_counts are silently dropped."""

    def test_unknown_category_ignored(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = 10
        raw = dict(counts)
        raw["unknown_future_category"] = 999  # not in SAFE_CATEGORIES
        agg = build_aggregate(_summary(counts=raw))
        # Drift key dropped — only 7 SAFE_CATEGORIES.
        self.assertEqual(set(agg["failure_category_counts"].keys()), set(SAFE_CATEGORIES))
        self.assertNotIn("unknown_future_category", agg["failure_category_counts"])
        self.assertEqual(agg["total_failures"], 10)

    def test_missing_failure_category_counts_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_aggregate({"num_predictions": 221, "abstention_outcomes": {}})


class TestMarkdownRender(unittest.TestCase):
    """Markdown surface contains the headline + contract + ranks."""

    def test_markdown_has_all_required_sections(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = 84
        counts["verifier_false_negative"] = 65
        counts["unknown"] = 28
        counts["verifier_false_positive"] = 1
        outcomes = {key: 0 for key in SAFE_OUTCOME_KEYS}
        outcomes["correct_refusal"] = 32
        outcomes["incorrect_answer"] = 65
        outcomes["boundary_partial"] = 6
        agg = build_aggregate(_summary(num_predictions=221, counts=counts, outcomes=outcomes))
        md = render_markdown(agg)
        self.assertIn("Failure-mode distribution (real100, n=221)", md)
        self.assertIn("Composition (% of failed cases)", md)
        self.assertIn("ADR 0059 first-match contract: ✓", md)
        self.assertIn("Refusal-axis cross-reference (PR #464, 3-bin)", md)
        # Rank 1 should be the dominant category (retrieval_miss=84).
        # Verify by searching for the count after the rank-1 row marker.
        self.assertIn("| 1 | `retrieval_miss` | 84 |", md)
        # incorrect_answer count appears in cross-reference table.
        self.assertIn("| `incorrect_answer` | 65 |", md)

    def test_markdown_flags_contract_violation(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["verifier_false_negative"] = 60
        outcomes = {key: 0 for key in SAFE_OUTCOME_KEYS}
        outcomes["incorrect_answer"] = 65
        md = render_markdown(build_aggregate(_summary(counts=counts, outcomes=outcomes)))
        self.assertIn("ADR 0059 first-match contract: ✗", md)
        self.assertIn("CONTRACT VIOLATED", md)


class TestEndToEndCLI(unittest.TestCase):
    """Main writes both artifacts to disk."""

    def test_writes_md_and_json(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = 84
        counts["verifier_false_negative"] = 65
        outcomes = {key: 0 for key in SAFE_OUTCOME_KEYS}
        outcomes["incorrect_answer"] = 65
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path = tmp_path / "eval_summary.json"
            md_path = tmp_path / "failure_distribution.md"
            json_path = tmp_path / "failure_distribution.aggregate.json"
            summary_path.write_text(
                json.dumps(_summary(counts=counts, outcomes=outcomes))
            )
            exit_code = main(
                [
                    "--summary",
                    str(summary_path),
                    "--out-md",
                    str(md_path),
                    "--out-json",
                    str(json_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            written = json.loads(json_path.read_text())
            self.assertEqual(written["total_failures"], 149)
            self.assertTrue(written["finding_1_contract"]["match"])

    def test_missing_summary_returns_nonzero(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exit_code = main(
                [
                    "--summary",
                    str(tmp_path / "nonexistent.json"),
                    "--out-md",
                    str(tmp_path / "x.md"),
                    "--out-json",
                    str(tmp_path / "x.json"),
                ]
            )
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
