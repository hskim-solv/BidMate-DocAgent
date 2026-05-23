"""Regression guards for single-doc topic grounding (issue #1008).

Phase 5 audit finding #1 (``docs/audits/verifier-false-negative-inspection.md``)
quantified ``verifier_false_negative`` as the #2 failure category: unanswerable
queries (``answerable=False``) that the verifier judged *sufficient* and so
answered instead of abstaining. 81.6% of those cases retrieved **multi-doc**
evidence whose verification topics were merely *scattered across unrelated
documents* — the combined-pool topic count in :func:`verify_evidence` treated
that cross-doc spread as full grounding.

The fix (issue #1008, audit hypothesis #2): for **non-comparison** queries the
verification topics must all be grounded *within a single document*. Comparison
queries legitimately span documents (one per entity) and keep the combined-pool
count, guarded by the existing entity/doc coverage checks.

These tests exercise the decision logic on synthetic evidence/analysis dicts so
the policy is locked independent of retrieval quality, matching the style of
``tests/test_partial_topic_grounding.py``.
"""

import unittest

from rag_verifier import (
    PARTIAL_TOPIC_GROUNDING_REASON,
    verify_evidence,
)


def _item(doc_id: str, text: str, score: float = 0.5) -> dict:
    return {"doc_id": doc_id, "chunk_id": doc_id + "::c1", "score": score, "text": text}


class CrossDocSpreadRejectedTest(unittest.TestCase):
    """The false-negative fix: cross-doc topic spread must NOT verify."""

    def test_cross_doc_spread_rejected_strict(self) -> None:
        """Topics split across two unrelated docs → topic_not_grounded.

        Pre-#1008 the combined pool contained both topics (2/2) → verified.
        After #1008 no single document grounds both → abstain. This is the
        exact verifier_false_negative pattern from the audit.
        """
        analysis = {"topics": ["보안 통제", "양자암호"]}
        evidence = [
            _item("doc-a", "이 문서는 보안 통제 요구사항을 다룬다."),
            _item("doc-b", "이 문서는 양자암호 표준을 설명한다."),
        ]
        verified, reasons = verify_evidence(analysis, evidence)
        self.assertFalse(verified, f"cross-doc spread must not verify; reasons={reasons}")
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_cross_doc_spread_not_recovered_as_partial_on_last_attempt(self) -> None:
        """Even on the relaxed last attempt, cross-doc spread stays an abstention.

        With max single-doc matches = 1 (< PARTIAL_TOPIC_GROUNDING_MIN_MATCHED),
        partial recovery cannot flip an unanswerable query to a `partial` answer.
        """
        analysis = {"topics": ["보안 통제", "양자암호"]}
        evidence = [
            _item("doc-a", "이 문서는 보안 통제 요구사항을 다룬다."),
            _item("doc-b", "이 문서는 양자암호 표준을 설명한다."),
        ]
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertFalse(verified, f"reasons={reasons}")
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_cross_doc_spread_respects_matched_doc_ids(self) -> None:
        """Single-doc grounding still honours the issue #687 cross-entity guard.

        When the query is mapped to a target doc and evidence comes from other
        docs, the single-doc count over the (empty) target pool is 0.
        """
        analysis = {
            "topics": ["보안 통제", "양자암호"],
            "matched_doc_ids": ["doc-target"],
        }
        evidence = [
            _item("doc-a", "이 문서는 보안 통제와 양자암호를 모두 다룬다."),
        ]
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertFalse(verified, f"reasons={reasons}")
        self.assertIn("topic_not_grounded", reasons)


class SingleDocGroundingPreservedTest(unittest.TestCase):
    """Answerable cases that genuinely ground in one doc must still verify."""

    def test_single_doc_full_grounding_verified(self) -> None:
        analysis = {"topics": ["보안 통제", "양자암호"]}
        evidence = [
            _item("doc-a", "이 문서는 보안 통제와 양자암호를 모두 다룬다."),
        ]
        verified, reasons = verify_evidence(analysis, evidence)
        self.assertTrue(verified, f"single-doc full grounding must verify; reasons={reasons}")
        self.assertNotIn("topic_not_grounded", reasons)

    def test_multi_chunk_same_doc_grounds_across_chunks(self) -> None:
        """Two chunks of the SAME doc jointly grounding the topics still verify.

        Single-doc grounding groups by ``doc_id``, so adjacent chunks of one
        document are pooled — only *cross-document* spread is rejected.
        """
        analysis = {"topics": ["보안 통제", "양자암호"]}
        evidence = [
            _item("doc-a::s1", "보안 통제 요구사항.", score=0.6),
            _item("doc-a::s2", "양자암호 표준.", score=0.55),
        ]
        # Same logical doc, distinct chunk ids but identical doc_id.
        evidence[0]["doc_id"] = "doc-a"
        evidence[1]["doc_id"] = "doc-a"
        verified, reasons = verify_evidence(analysis, evidence)
        self.assertTrue(verified, f"same-doc multi-chunk must verify; reasons={reasons}")
        self.assertNotIn("topic_not_grounded", reasons)

    def test_single_doc_partial_recovery_preserved(self) -> None:
        """3-of-4 topics within one doc still recovers as `partial` (issue #69)."""
        analysis = {"topics": ["보안 통제", "로그 추적", "감사 로그", "양자암호"]}
        evidence = [
            _item("doc-a", "이 문서는 보안 통제와 로그 추적, 감사 로그를 다룬다."),
        ]
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertTrue(verified, f"reasons={reasons}")
        self.assertIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)
        self.assertNotIn("topic_not_grounded", reasons)


class ComparisonExemptionTest(unittest.TestCase):
    """Comparison queries keep cross-doc grounding (one document per entity)."""

    def test_comparison_allows_cross_doc_topic_grounding(self) -> None:
        analysis = {
            "query_type": "comparison",
            "topics": ["보안 통제", "양자암호"],
            "entities": [],
        }
        evidence = [
            _item("doc-a", "기관 A의 보안 통제 요구사항."),
            _item("doc-b", "기관 B의 양자암호 표준."),
        ]
        verified, reasons = verify_evidence(analysis, evidence)
        self.assertTrue(
            verified,
            f"comparison must keep combined-pool grounding; reasons={reasons}",
        )
        self.assertNotIn("topic_not_grounded", reasons)


if __name__ == "__main__":
    unittest.main()
