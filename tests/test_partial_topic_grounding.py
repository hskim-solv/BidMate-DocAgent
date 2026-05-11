"""Behavioral guards for partial-topic grounding (issues #69 and #89).

Covers two complementary expectations from ``docs/real-data-failure-taxonomy.md``
C6 ("false abstention"):

* **Recovery** — when verification topics are only partially matched in
  the evidence, the *relaxed* (last-attempt) verifier accepts the result
  with a non-blocking ``partial_topic_grounding`` reason, and the answer
  surfaces as ``partial`` instead of an unconditional abstention.
* **Preservation** — when no relevant evidence exists (out-of-corpus
  query), abstention is preserved. Partial-topic mode must not turn
  unanswerable queries into hallucinated ``partial`` answers. Issue #89
  added a ``≥ 2 matched topics`` floor on top of the fraction floor to
  cut the 1-of-2 incidental-overlap pattern that flipped real-data
  intended-abstention cases after #69.

Both tests use the deterministic hashing embedding backend on the
existing ``data/raw`` fixture, matching the pattern in
``tests/test_retrieval_loop_regression.py``.
"""

import unittest
from pathlib import Path

from rag_core import (
    PARTIAL_TOPIC_GROUNDING_MIN_FRACTION,
    PARTIAL_TOPIC_GROUNDING_MIN_MATCHED,
    PARTIAL_TOPIC_GROUNDING_REASON,
    build_index_payload,
    verify_evidence,
)


class VerifyEvidencePartialTopicTest(unittest.TestCase):
    """Unit-level checks against :func:`verify_evidence` semantics.

    These do not need the index — they exercise the decision logic on
    synthetic evidence/analysis dicts so the policy is locked in
    independent of retrieval quality.
    """

    def _evidence(self, text: str, score: float = 0.5) -> list[dict]:
        return [
            {
                "doc_id": "doc-x",
                "chunk_id": "c1",
                "score": score,
                "text": text,
            }
        ]

    def test_strict_rejects_partial_topic_match(self) -> None:
        analysis = {"topics": ["보안 통제", "로그 추적"]}
        evidence = self._evidence("이 문서는 보안 통제만 다룬다.")
        verified, reasons = verify_evidence(analysis, evidence)
        self.assertFalse(verified)
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_relaxed_accepts_partial_topic_match_above_threshold(self) -> None:
        # ≥ FRACTION AND ≥ MIN_MATCHED matched topics → accepted in
        # relaxed mode. After issue #89's tightening, the gate also
        # requires at least PARTIAL_TOPIC_GROUNDING_MIN_MATCHED matched
        # topics, so we exercise a 3-of-4 = 0.75 profile that satisfies
        # both the fraction floor and the matched-count floor.
        analysis = {"topics": ["보안 통제", "로그 추적", "감사 로그", "양자암호"]}
        evidence = self._evidence(
            "이 문서는 보안 통제와 로그 추적, 그리고 감사 로그를 다룬다."
        )
        self.assertGreaterEqual(3 / 4, PARTIAL_TOPIC_GROUNDING_MIN_FRACTION)
        self.assertGreaterEqual(3, PARTIAL_TOPIC_GROUNDING_MIN_MATCHED)
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertTrue(verified, f"reasons={reasons}")
        self.assertIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)
        self.assertNotIn("topic_not_grounded", reasons)

    def test_relaxed_rejects_one_of_two_partial_topic_match(self) -> None:
        """Issue #89 regression guard.

        Pre-#89 the gate accepted a 1-of-2 partial overlap in relaxed
        mode (1/2 = 0.5 ≥ 0.5 AND matched ≥ 1). On real data this
        flipped intended-abstention queries that share one incidental
        topic-token with in-corpus content (e.g. an out-of-corpus
        query whose first token matches a metadata term). The
        :data:`PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` floor cuts this
        deterministically.
        """
        analysis = {"topics": ["보안 통제", "양자암호"]}
        evidence = self._evidence("기관 A의 보안 통제 요구사항은 다음과 같다.")
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        # 1/2 == 0.5 satisfies the fraction floor but fails the
        # matched-count floor (1 < PARTIAL_TOPIC_GROUNDING_MIN_MATCHED).
        self.assertLess(1, PARTIAL_TOPIC_GROUNDING_MIN_MATCHED)
        self.assertFalse(verified, f"reasons={reasons}")
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_relaxed_still_rejects_zero_topic_match(self) -> None:
        analysis = {"topics": ["보안 통제", "로그 추적"]}
        evidence = self._evidence("관련 없는 내용만 있는 문단이다.")
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        # No topic matched → strict reject even in relaxed stage so
        # unanswerable / out-of-corpus queries keep abstaining.
        self.assertFalse(verified)
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_relaxed_still_rejects_below_fraction(self) -> None:
        analysis = {"topics": ["보안 통제", "로그 추적", "암호화", "감사"]}
        evidence = self._evidence("이 문서는 보안 통제만 다룬다.")
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        # 1/4 == 0.25 < PARTIAL_TOPIC_GROUNDING_MIN_FRACTION (0.5).
        self.assertLess(1 / 4, PARTIAL_TOPIC_GROUNDING_MIN_FRACTION)
        self.assertFalse(verified)
        self.assertIn("topic_not_grounded", reasons)

    def test_low_top_score_still_blocking_in_relaxed_stage(self) -> None:
        analysis = {"topics": ["보안 통제"]}
        evidence = self._evidence("이 문서는 보안 통제를 다룬다.", score=0.05)
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        # Hallucination floor must hold even in relaxed mode.
        self.assertFalse(verified)
        self.assertIn("low_top_score", reasons)


class OutOfCorpusAbstentionPreservedTest(unittest.TestCase):
    """End-to-end guard: out-of-corpus queries still abstain.

    This is the regression-safety side of issue #69 — the policy
    change must not flip intended abstentions into ``partial`` answers.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def test_out_of_corpus_query_still_abstains(self) -> None:
        from rag_core import run_rag_query

        result = run_rag_query(
            self.index, "외계 행성의 우주선 검수 절차는?"
        )
        self.assertEqual(result["answer"]["status"], "insufficient")
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
