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
    case_results: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a minimal eval_summary.json-shaped dict.

    Only the top-level keys the renderer reads are populated;
    fixtures stay small enough that schema drift surfaces as a test
    failure rather than silently passing.
    """
    summary: dict[str, object] = {
        "num_predictions": num_predictions,
        "failure_category_counts": counts or {category: 0 for category in SAFE_CATEGORIES},
        "abstention_outcomes": outcomes or {key: 0 for key in SAFE_OUTCOME_KEYS},
    }
    if case_results is not None:
        summary["case_results"] = case_results
    return summary


def _vfn_case(**overrides: object) -> dict[str, object]:
    """A case_result that classify_failure routes to verifier_false_negative.

    (answerable=False AND abstained=False — first-match branch 1.)
    """
    base: dict[str, object] = {
        "answerable": False,
        "abstained": False,
        "query_type": "abstention",
        "hardcase_categories": ["no_answer"],
        "evidence_doc_ids": ["d1", "d2"],
        "expected_doc_ids": [],
        "retry_count": 1,
        "query": "예산은 얼마인가요?",
        "term_match": False,
        "doc_match": False,
    }
    base.update(overrides)
    return base


def _retrieval_miss_case(**overrides: object) -> dict[str, object]:
    """A case_result that classify_failure routes to retrieval_miss.

    (answerable=True, accuracy<1, expected docs never reached evidence.)
    """
    base: dict[str, object] = {
        "answerable": True,
        "accuracy": 0.0,
        "abstained": False,
        "query_type": "single_doc",
        "hardcase_categories": ["multi_hop", "distractor_heavy"],
        "evidence_doc_ids": ["other"],
        "expected_doc_ids": ["gold"],
        "retry_count": 0,
        "query": "사업 기간 명시",
        "term_match": False,
        "doc_match": False,
    }
    base.update(overrides)
    return base


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
        self.assertIn("slice_counts", agg)
        self.assertEqual(agg["schema_version"], 2)

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
    """Taxonomy drift in failure_category_counts must fail loud, not silent-drop."""

    def test_unknown_category_raises(self) -> None:
        # A key outside FAILURE_CATEGORIES means the classifier taxonomy drifted.
        # Silently dropping it would undercount total_failures (the original
        # bug: {retrieval_miss:1, new_category:1} reported total 1, not 2).
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = 10
        raw = dict(counts)
        raw["unknown_future_category"] = 999  # not in FAILURE_CATEGORIES
        with self.assertRaises(ValueError) as ctx:
            build_aggregate(_summary(counts=raw))
        self.assertIn("unknown_future_category", str(ctx.exception))

    def test_total_failures_not_undercounted_on_drift(self) -> None:
        # Regression for the silent-drop total bug: an out-of-taxonomy key
        # must not be quietly excluded from the sum.
        with self.assertRaises(ValueError):
            build_aggregate(_summary(counts={"retrieval_miss": 1, "new_category": 1}))

    def test_non_numeric_count_raises(self) -> None:
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = "lots"  # type: ignore[assignment]
        with self.assertRaises(ValueError):
            build_aggregate(_summary(counts=counts))

    def test_bool_count_rejected(self) -> None:
        # bool is an int subclass; a True/False "count" is a schema error.
        counts = {category: 0 for category in SAFE_CATEGORIES}
        counts["retrieval_miss"] = True  # type: ignore[assignment]
        with self.assertRaises(ValueError):
            build_aggregate(_summary(counts=counts))

    def test_taxonomy_matches_classifier_single_source(self) -> None:
        # SAFE_CATEGORIES must BE the classifier taxonomy (no hardcoded copy).
        from eval.scorers.failure_classifier import FAILURE_CATEGORIES

        self.assertEqual(SAFE_CATEGORIES, FAILURE_CATEGORIES)

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


class TestSliceCountsShape(unittest.TestCase):
    """slice_counts always has all 7 categories with the full sub-shape."""

    def test_all_categories_zeroed_when_no_case_results(self) -> None:
        agg = build_aggregate(_summary())
        slices = agg["slice_counts"]
        self.assertEqual(set(slices.keys()), set(SAFE_CATEGORIES))
        vfn = slices["verifier_false_negative"]
        self.assertEqual(vfn["n"], 0)
        # Full sub-shape present even with no data.
        for dim in (
            "query_type",
            "hardcase_categories",
            "evidence_cardinality",
            "expected_doc_coverage",
            "retry_count",
            "query_specificity",
            "aux_true",
        ):
            self.assertIn(dim, vfn)

    def test_per_category_n_matches_classifier(self) -> None:
        # 2 verifier_false_negative + 1 retrieval_miss.
        cases = [_vfn_case(), _vfn_case(), _retrieval_miss_case()]
        agg = build_aggregate(_summary(case_results=cases))
        slices = agg["slice_counts"]
        self.assertEqual(slices["verifier_false_negative"]["n"], 2)
        self.assertEqual(slices["retrieval_miss"]["n"], 1)
        self.assertEqual(slices["unknown"]["n"], 0)


class TestSliceCountsAccumulation(unittest.TestCase):
    """Each slice dimension counts the right buckets."""

    def test_dimensions_count_correctly(self) -> None:
        cases = [
            _vfn_case(
                hardcase_categories=["no_answer", "long_context"],
                evidence_doc_ids=["a", "b"],  # multi-doc
                expected_doc_ids=[],  # no_expected
                retry_count=1,
                query="예산은 얼마인가요?",  # specificity hit
                abstained=False,
                term_match=False,
            ),
            _vfn_case(
                hardcase_categories=["no_answer"],
                evidence_doc_ids=["a"],  # single-doc
                expected_doc_ids=["a"],  # expected_in_evidence
                retry_count=0,
                query="사업 기간은?",  # no specificity hit
                term_match=True,
            ),
        ]
        vfn = build_aggregate(_summary(case_results=cases))["slice_counts"][
            "verifier_false_negative"
        ]
        self.assertEqual(vfn["query_type"]["abstention"], 2)
        self.assertEqual(vfn["hardcase_categories"]["no_answer"], 2)
        self.assertEqual(vfn["hardcase_categories"]["long_context"], 1)
        self.assertEqual(vfn["evidence_cardinality"]["multi_doc"], 1)
        self.assertEqual(vfn["evidence_cardinality"]["single_doc"], 1)
        self.assertEqual(vfn["expected_doc_coverage"]["no_expected"], 1)
        self.assertEqual(vfn["expected_doc_coverage"]["expected_in_evidence"], 1)
        self.assertEqual(vfn["retry_count"]["1"], 1)
        self.assertEqual(vfn["retry_count"]["0"], 1)
        self.assertEqual(vfn["query_specificity"]["keyword_hit"], 1)
        self.assertEqual(vfn["query_specificity"]["no_hit"], 1)
        self.assertEqual(vfn["aux_true"]["term_match"], 1)

    def test_expected_not_in_evidence(self) -> None:
        rm = build_aggregate(
            _summary(case_results=[_retrieval_miss_case()])
        )["slice_counts"]["retrieval_miss"]
        self.assertEqual(rm["expected_doc_coverage"]["expected_not_in_evidence"], 1)
        self.assertEqual(rm["hardcase_categories"]["multi_hop"], 1)
        self.assertEqual(rm["hardcase_categories"]["distractor_heavy"], 1)

    def test_retry_count_3plus_bucket(self) -> None:
        vfn = build_aggregate(
            _summary(case_results=[_vfn_case(retry_count=5)])
        )["slice_counts"]["verifier_false_negative"]
        self.assertEqual(vfn["retry_count"]["3plus"], 1)


class TestSliceFailClosed(unittest.TestCase):
    """#1286 guard — non-whitelisted enum values bucket into other/untagged,
    never a fresh dict key carrying a raw private string."""

    def test_unknown_query_type_and_hardcase_bucket_to_other(self) -> None:
        case = _vfn_case(
            query_type="some_private_query_type_xyz",
            hardcase_categories=["secret_tag_not_in_enum"],
        )
        vfn = build_aggregate(_summary(case_results=[case]))["slice_counts"][
            "verifier_false_negative"
        ]
        self.assertEqual(vfn["query_type"]["other"], 1)
        self.assertNotIn("some_private_query_type_xyz", vfn["query_type"])
        self.assertEqual(vfn["hardcase_categories"]["other"], 1)
        self.assertNotIn("secret_tag_not_in_enum", vfn["hardcase_categories"])

    def test_empty_hardcase_is_untagged(self) -> None:
        vfn = build_aggregate(
            _summary(case_results=[_vfn_case(hardcase_categories=[])])
        )["slice_counts"]["verifier_false_negative"]
        self.assertEqual(vfn["hardcase_categories"]["untagged"], 1)


class TestSliceNoPrivateLeak(unittest.TestCase):
    """ADR 0005 — no raw query text or doc id ever reaches the aggregate."""

    def test_raw_strings_absent_from_serialized_aggregate(self) -> None:
        secret_query = "주식회사 비밀기관 2026 예산 얼마 구체적으로"
        secret_doc = "agency-secret-공고-12345"
        case = _vfn_case(
            query=secret_query,
            evidence_doc_ids=[secret_doc],
            expected_doc_ids=[secret_doc],
        )
        agg = build_aggregate(_summary(case_results=[case]))
        blob = json.dumps(agg, ensure_ascii=False)
        self.assertNotIn(secret_query, blob)
        self.assertNotIn(secret_doc, blob)
        self.assertNotIn("비밀기관", blob)
        # The count still registered — specificity keyword matched.
        vfn = agg["slice_counts"]["verifier_false_negative"]
        self.assertEqual(vfn["query_specificity"]["keyword_hit"], 1)

    def test_markdown_has_no_private_strings(self) -> None:
        secret_query = "비밀쿼리텍스트 얼마"
        secret_doc = "secret-doc-id-zzz"
        agg = build_aggregate(
            _summary(
                case_results=[
                    _vfn_case(
                        query=secret_query,
                        evidence_doc_ids=[secret_doc],
                        expected_doc_ids=[secret_doc],
                    )
                ]
            )
        )
        md = render_markdown(agg)
        self.assertNotIn(secret_query, md)
        self.assertNotIn(secret_doc, md)
        self.assertIn("Per-category slices", md)


if __name__ == "__main__":
    unittest.main()
