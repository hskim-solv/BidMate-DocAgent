"""Regression guard for the per-category failure-slice renderer (issue #1243).

Verifies slice math, the ``_untagged`` hardcase bucket, success-case
exclusion, and the ADR 0005 boundary (counts only — no raw text / doc_id /
chunk_id ever reaches the committed aggregate). Stub eval_summary inputs
only; no real-eval dependency.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.render_failure_slices import (
    UNTAGGED,
    build_aggregate,
    main,
)


def _case(
    *,
    failure_category: str | None,
    query_type: str = "single_doc",
    hardcase: list[str] | None = None,
    expected_doc_ids: list[str] | None = None,
    evidence_doc_ids: list[str] | None = None,
    abstained: bool = False,
    term_match: bool = False,
    doc_match: bool = False,
    retry_count: int = 0,
) -> dict[str, object]:
    return {
        "failure_category": failure_category,
        "query_type": query_type,
        "hardcase_categories": hardcase if hardcase is not None else [],
        "expected_doc_ids": expected_doc_ids if expected_doc_ids is not None else ["d1"],
        "evidence_doc_ids": evidence_doc_ids if evidence_doc_ids is not None else [],
        "abstained": abstained,
        "term_match": term_match,
        "doc_match": doc_match,
        "retry_count": retry_count,
    }


def _summary(cases: list[dict[str, object]]) -> dict[str, object]:
    return {"num_predictions": len(cases), "case_results": cases}


class BuildAggregateTest(unittest.TestCase):
    def test_slice_counts(self) -> None:
        cases = [
            _case(failure_category="retrieval_miss", query_type="single_doc",
                  hardcase=["multi_hop", "distractor_heavy"],
                  evidence_doc_ids=["wrong"], doc_match=False, retry_count=1),
            _case(failure_category="retrieval_miss", query_type="follow_up",
                  hardcase=["multi_hop"], evidence_doc_ids=[], doc_match=False),
            _case(failure_category="retrieval_miss", query_type="single_doc",
                  hardcase=[], abstained=True, term_match=True, retry_count=1),
        ]
        agg = build_aggregate(_summary(cases))
        rm = agg["categories"]["retrieval_miss"]

        self.assertEqual(rm["total"], 3)
        self.assertEqual(rm["by_query_type"], {"single_doc": 2, "follow_up": 1})
        self.assertEqual(
            rm["by_hardcase"],
            {"multi_hop": 2, "distractor_heavy": 1, UNTAGGED: 1},
        )
        self.assertEqual(rm["by_expected_cardinality"], {"1": 3})
        self.assertEqual(rm["by_evidence_presence"], {"empty": 2, "non_empty": 1})
        self.assertEqual(
            rm["aux"],
            {
                "abstained_true": 1,
                "term_match_true": 1,
                "doc_match_false": 3,
                "retry_count_eq_1": 2,
            },
        )

    def test_successes_and_other_categories_excluded(self) -> None:
        cases = [
            _case(failure_category=None),  # success — excluded
            _case(failure_category="verifier_false_negative"),  # other bucket
            _case(failure_category="retrieval_miss"),
        ]
        agg = build_aggregate(_summary(cases))
        self.assertEqual(set(agg["categories"]), {"verifier_false_negative", "retrieval_miss"})
        self.assertEqual(agg["categories"]["retrieval_miss"]["total"], 1)

    def test_missing_case_results_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_aggregate({"num_predictions": 0})

    def test_adr0005_boundary_counts_only(self) -> None:
        """No raw text / doc_id value may surface — only counts + bucket labels."""
        cases = [
            _case(failure_category="retrieval_miss",
                  expected_doc_ids=["SECRET_DOC_42"],
                  evidence_doc_ids=["SECRET_DOC_99"]),
        ]
        agg = build_aggregate(_summary(cases))
        blob = json.dumps(agg)
        self.assertNotIn("SECRET_DOC", blob)
        # Every leaf under aux / presence / cardinality is an int.
        rm = agg["categories"]["retrieval_miss"]
        for value in rm["aux"].values():
            self.assertIsInstance(value, int)


class MainCliTest(unittest.TestCase):
    def test_main_writes_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "eval_summary.json"
            out_path = Path(tmp) / "failure_slices.aggregate.json"
            summary_path.write_text(json.dumps(_summary([
                _case(failure_category="retrieval_miss"),
            ])))
            rc = main(["--summary", str(summary_path), "--out-json", str(out_path)])
            self.assertEqual(rc, 0)
            written = json.loads(out_path.read_text())
            self.assertEqual(written["categories"]["retrieval_miss"]["total"], 1)
            self.assertEqual(written["schema_version"], 1)

    def test_main_missing_summary_returns_1(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = main(["--summary", str(Path(tmp) / "nope.json")])
            self.assertEqual(rc, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
