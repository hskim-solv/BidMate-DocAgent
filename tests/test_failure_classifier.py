"""ADR 0075 — normalized failure-mode classifier regression guard."""
from __future__ import annotations

import unittest

from eval.scorers.failure_classifier import (
    FAILURE_CATEGORIES,
    aggregate_failure_categories,
    classify_failure,
    is_failed,
)


def _case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "case",
        "answerable": True,
        "accuracy": 0.0,
        "abstained": False,
        "expected_doc_ids": ["doc_a"],
        "gold_chunk_ids": ["doc_a:0"],
        "gold_evidence": [{"doc_id": "doc_a", "chunk_id": "doc_a:0"}],
        "evidence_doc_ids": ["doc_a"],
        "retrieved_chunk_ids": ["doc_a:0"],
        "chunk_recall_at_10": 1.0,
        "doc_match": True,
        "term_match": False,
        "citation_term_match": True,
        "citation_precision": 1.0,
        "claim_citation_alignment": 1.0,
    }
    base.update(overrides)
    return base


class TaxonomyShapeTest(unittest.TestCase):
    def test_categories_are_normalized(self) -> None:
        self.assertEqual(
            FAILURE_CATEGORIES,
            (
                "retrieval_miss",
                "citation_or_page_metadata_issue",
                "verifier_false_negative",
                "verifier_false_positive",
                "answer_synthesis_issue",
                "abstention_failure",
                "evaluation_label_issue",
                "parse_or_metadata_issue",
                "unknown",
            ),
        )


class SuccessBoundaryTest(unittest.TestCase):
    def test_successful_answerable_returns_none(self) -> None:
        case = _case(accuracy=1.0)
        self.assertFalse(is_failed(case))
        self.assertIsNone(classify_failure(case))

    def test_correct_refusal_returns_none(self) -> None:
        case = _case(
            answerable=False,
            abstained=True,
            abstention=1.0,
            accuracy=None,
            expected_doc_ids=[],
            gold_chunk_ids=[],
            gold_evidence=[],
            evidence_doc_ids=[],
        )
        self.assertFalse(is_failed(case))
        self.assertIsNone(classify_failure(case))


class NormalizedCategoryTest(unittest.TestCase):
    def test_evaluation_label_issue_for_missing_gold_labels(self) -> None:
        case = _case(expected_doc_ids=[], gold_chunk_ids=[], gold_evidence=[])
        self.assertEqual(classify_failure(case), "evaluation_label_issue")

    def test_verifier_false_negative_for_unanswerable_answered(self) -> None:
        case = _case(
            answerable=False,
            abstained=False,
            abstention=0.0,
            accuracy=None,
            expected_doc_ids=[],
            gold_chunk_ids=[],
            gold_evidence=[],
            evidence_doc_ids=["doc_noise"],
        )
        self.assertEqual(classify_failure(case), "verifier_false_negative")

    def test_verifier_false_positive_for_refusal_with_full_evidence(self) -> None:
        case = _case(abstained=True, expected_doc_ids=["doc_a"], evidence_doc_ids=["doc_a"])
        self.assertEqual(classify_failure(case), "verifier_false_positive")

    def test_boundary_partial_is_abstention_failure(self) -> None:
        case = _case(
            answerable=False,
            abstained=True,
            abstention=1.0,
            accuracy=None,
            expected_doc_ids=[],
            gold_chunk_ids=[],
            gold_evidence=[],
            evidence_doc_ids=["doc_noise"],
        )
        self.assertTrue(is_failed(case))
        self.assertEqual(classify_failure(case), "abstention_failure")

    def test_answerable_refusal_with_partial_evidence_is_abstention_failure(self) -> None:
        case = _case(
            abstained=True,
            expected_doc_ids=["doc_a", "doc_b"],
            evidence_doc_ids=["doc_a"],
            citation_term_match=False,
        )
        self.assertEqual(classify_failure(case), "abstention_failure")

    def test_parse_or_metadata_issue_from_metadata_ambiguity(self) -> None:
        case = _case(metadata_ambiguous=True, evidence_doc_ids=[])
        self.assertEqual(classify_failure(case), "parse_or_metadata_issue")

    def test_retrieval_miss_for_missing_expected_doc(self) -> None:
        case = _case(evidence_doc_ids=["doc_b"], retrieved_chunk_ids=["doc_b:0"])
        self.assertEqual(classify_failure(case), "retrieval_miss")

    def test_retrieval_miss_for_missing_gold_chunk(self) -> None:
        case = _case(
            expected_doc_ids=[],
            gold_chunk_ids=["doc_a:gold"],
            gold_evidence=[{"doc_id": "doc_a", "chunk_id": "doc_a:gold"}],
            evidence_doc_ids=[],
            retrieved_chunk_ids=["doc_a:other"],
            chunk_recall_at_10=0.0,
        )
        self.assertEqual(classify_failure(case), "retrieval_miss")

    def test_citation_or_page_metadata_issue_for_missing_citation_term(self) -> None:
        case = _case(citation_term_match=False)
        self.assertEqual(classify_failure(case), "citation_or_page_metadata_issue")

    def test_citation_or_page_metadata_issue_for_page_mismatch(self) -> None:
        case = _case(
            citation_grounding_errors=[{"code": "page_mismatch"}],
            citation_page_precision=0.0,
        )
        self.assertEqual(classify_failure(case), "citation_or_page_metadata_issue")

    def test_answer_synthesis_issue_for_supported_evidence_wrong_answer(self) -> None:
        case = _case(term_match=False, citation_term_match=True, claim_citation_alignment=1.0)
        self.assertEqual(classify_failure(case), "answer_synthesis_issue")

    def test_answer_synthesis_issue_for_low_claim_alignment(self) -> None:
        case = _case(claim_citation_alignment=0.0)
        self.assertEqual(classify_failure(case), "answer_synthesis_issue")

    def test_unknown_is_residual_fallback(self) -> None:
        case = _case(doc_match=False, term_match=True, citation_term_match=True)
        self.assertEqual(classify_failure(case), "unknown")

    def test_rules_do_not_need_raw_query_or_answer_text(self) -> None:
        case = _case(evidence_doc_ids=["doc_b"], retrieved_chunk_ids=["doc_b:0"])
        case.pop("query", None)
        case.pop("answer", None)
        case.pop("evidence", None)
        self.assertEqual(classify_failure(case), "retrieval_miss")


class AggregateFailureCategoriesTest(unittest.TestCase):
    def test_counts_match_normalized_taxonomy(self) -> None:
        cases = [
            _case(evidence_doc_ids=["doc_b"]),
            _case(answerable=False, abstained=False, abstention=0.0, accuracy=None),
            _case(
                answerable=False,
                abstained=True,
                abstention=1.0,
                accuracy=None,
                evidence_doc_ids=["doc_noise"],
                expected_doc_ids=[],
                gold_chunk_ids=[],
                gold_evidence=[],
            ),
            _case(accuracy=1.0),
        ]
        counts = aggregate_failure_categories(cases)

        self.assertEqual(set(counts), set(FAILURE_CATEGORIES))
        self.assertEqual(counts["retrieval_miss"], 1)
        self.assertEqual(counts["verifier_false_negative"], 1)
        self.assertEqual(counts["abstention_failure"], 1)
        self.assertEqual(sum(counts.values()), 3)
        self.assertEqual(counts["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
