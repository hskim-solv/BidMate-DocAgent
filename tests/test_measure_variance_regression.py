"""Regression guards for `scripts/measure_variance.py` (issue #1235).

Two latent bugs found by the codex adversarial-review loop (idx49,
commit 63993b7, #1025 re-issue). The committed aggregate
(`reports/real100/variance_measurement/aggregate.json`) survived only by
luck — its 221 cases happen to have unique 64-char query prefixes — but
both bugs silently corrupt or hide on reuse.

* **F1** — `_per_case_categories` read a dead key `case_id` (+ a
  `query[:64]` surrogate). The real case-id key in `case_results` entries
  is `id` (eval/scorers/case.py), so every case fell back to the prefix
  surrogate and any two cases sharing a 64-char prefix would merge.
* **F2** — `_category_counts` / `_contract_check` used `or {}` / `or []`
  fallbacks, so a wrong glob (this script's own aggregate.json, a
  pre-ADR-0059 summary) parsed into all-zero counts + a 0==0 contract-ok
  and exited cleanly. Part of the measurement fail-open theme (idx39/40/42).
"""

from __future__ import annotations

import unittest

from scripts.measure_variance import (
    _category_counts,
    _contract_check,
    _per_case_categories,
    _validate_run,
    build_aggregate,
)


def _valid_run(case_results: list[dict] | None = None) -> dict:
    """A minimally-valid eval_summary.json shape."""
    if case_results is None:
        case_results = [
            {"id": "c1", "answerable": True, "failure_category": "retrieval_miss"},
            {"id": "c2", "answerable": True, "failure_category": None},
        ]
    return {
        "failure_category_counts": {
            "retrieval_miss": 1,
            "citation_or_page_metadata_issue": 0,
            "verifier_false_negative": 2,
            "verifier_false_positive": 0,
            "answer_synthesis_issue": 0,
            "abstention_failure": 0,
            "evaluation_label_issue": 0,
            "parse_or_metadata_issue": 0,
            "unknown": 0,
        },
        "abstention_outcomes": {
            "correct_refusal": 0,
            "incorrect_answer": 2,
            "boundary_partial": 0,
        },
        "case_results": case_results,
    }


class PerCaseMatchTest(unittest.TestCase):
    """F1: id-based matching must not merge prefix-colliding cases."""

    def test_distinct_ids_sharing_64char_query_prefix_not_merged(self) -> None:
        prefix = "동일한_쿼리_접두사_" * 8  # > 64 chars, identical for both
        run = _valid_run(
            case_results=[
                {"id": "case-A", "query": prefix + "AAA", "failure_category": "retrieval_miss"},
                {"id": "case-B", "query": prefix + "BBB", "failure_category": "unknown"},
            ]
        )
        result = _per_case_categories(run, "run.json")
        self.assertEqual(set(result), {"case-A", "case-B"})
        self.assertEqual(result["case-A"], "retrieval_miss")
        self.assertEqual(result["case-B"], "unknown")

    def test_missing_id_fails_closed(self) -> None:
        run = _valid_run(case_results=[{"query": "q", "failure_category": "unknown"}])
        with self.assertRaises(SystemExit):
            _per_case_categories(run, "run.json")

    def test_duplicate_id_fails_closed(self) -> None:
        run = _valid_run(
            case_results=[
                {"id": "dup", "failure_category": "retrieval_miss"},
                {"id": "dup", "failure_category": "unknown"},
            ]
        )
        with self.assertRaises(SystemExit):
            _per_case_categories(run, "run.json")

    def test_null_failure_category_maps_to_success(self) -> None:
        run = _valid_run(case_results=[{"id": "c1", "failure_category": None}])
        self.assertEqual(_per_case_categories(run, "run.json"), {"c1": "success"})


class FieldGuardTest(unittest.TestCase):
    """F2: missing/wrong-shape fields must fail loud, not parse as zero."""

    def test_valid_run_passes(self) -> None:
        _validate_run("run.json", _valid_run())  # no raise

    def test_missing_failure_category_counts_fails(self) -> None:
        run = _valid_run()
        del run["failure_category_counts"]
        with self.assertRaises(SystemExit):
            _validate_run("run.json", run)

    def test_incomplete_category_dict_fails(self) -> None:
        run = _valid_run()
        del run["failure_category_counts"]["unknown"]
        with self.assertRaises(SystemExit):
            _validate_run("run.json", run)

    def test_empty_case_results_fails(self) -> None:
        run = _valid_run(case_results=[])
        with self.assertRaises(SystemExit):
            _validate_run("run.json", run)

    def test_missing_abstention_incorrect_answer_fails(self) -> None:
        run = _valid_run()
        del run["abstention_outcomes"]["incorrect_answer"]
        with self.assertRaises(SystemExit):
            _validate_run("run.json", run)

    def test_aggregate_json_glob_self_match_rejected(self) -> None:
        """The script's own aggregate.json lacks the run-shape keys."""
        wrong = {"schema_version": 1, "n_runs": 3, "per_case_stability": {}}
        with self.assertRaises(SystemExit):
            _validate_run("aggregate.json", wrong)


class StrictAccessorTest(unittest.TestCase):
    """The strict (no `or {}`) accessors return correct values on valid input."""

    def test_category_counts_and_contract(self) -> None:
        run = _valid_run()
        self.assertEqual(_category_counts(run)["verifier_false_negative"], 2)
        vfn, inc, ok = _contract_check(run)
        self.assertEqual((vfn, inc), (2, 2))
        self.assertTrue(ok)

    def test_build_aggregate_counts_distinct_cases(self) -> None:
        run = _valid_run(
            case_results=[
                {"id": "c1", "failure_category": "retrieval_miss"},
                {"id": "c2", "failure_category": "unknown"},
            ]
        )
        agg = build_aggregate([("r1.json", run), ("r2.json", run)])
        self.assertEqual(agg["per_case_stability"]["total_cases"], 2)
        self.assertEqual(agg["per_case_stability"]["stable"], 2)


if __name__ == "__main__":
    unittest.main()
