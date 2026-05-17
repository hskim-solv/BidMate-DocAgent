"""Behavioral guards for partial-topic grounding (issues #69 and #89).

Covers two complementary expectations from ``docs/real-data/real-data-failure-taxonomy.md``
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
from tests._shared_index_cache import get_shared_raw_index


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
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index()

    def test_out_of_corpus_query_still_abstains(self) -> None:
        from rag_core import run_rag_query

        result = run_rag_query(
            self.index, "외계 행성의 우주선 검수 절차는?"
        )
        self.assertEqual(result["answer"]["status"], "insufficient")
        self.assertEqual(result["evidence"], [])


class WhQueryTokenExclusionTest(unittest.TestCase):
    """Regression guards for issue #674 — WH-interrogatives, postpositions,
    and verb endings must not become verification topics (they never appear
    verbatim in RFP document text, so they inflate the topic list and push
    the grounded fraction below PARTIAL_TOPIC_GROUNDING_MIN_FRACTION).

    probe_11 scenario: "고양도시관리공사 다목적구장 홈페이지 사업이 며칠 안에 마무리돼?"
    - raw topics include '며칠', '안에', '마무리돼'  (WH / postposition / verb ending)
    - gold chunk contains '착수일로부터 90일 이내' but NOT the WH-form words
    - before fix: 2/6 = 0.33 < 0.5 → topic_not_grounded (wrong abstention)
    - after fix:  2/3 = 0.67 ≥ 0.5 AND matched ≥ 2 → partial_topic_grounding pass
    """

    def test_wh_tokens_excluded_from_verification_topics(self) -> None:
        """며칠 / 안에 / 마무리돼 are filtered out of verification_topics."""
        from rag_verifier import verification_topics

        analysis = {
            "topics": [
                "고양도시관리공사", "다목적구장", "홈페이지",
                "며칠", "안에", "마무리돼",
            ]
        }
        result = verification_topics(analysis)
        for excluded in ("며칠", "안에", "마무리돼"):
            self.assertNotIn(
                excluded, result,
                f"WH/postposition/verb token {excluded!r} should be excluded",
            )
        for kept in ("고양도시관리공사", "다목적구장"):
            self.assertIn(kept, result, f"substantive topic {kept!r} should be kept")

    def test_other_wh_words_excluded(self) -> None:
        """Sample of other WH-query tokens that must not become topics."""
        from rag_verifier import verification_topics

        wh_words = ["언제", "어디", "왜", "몇", "뭐", "어느", "이내", "이후", "이전"]
        analysis = {"topics": ["예산", "기관명"] + wh_words}
        result = verification_topics(analysis)
        for wh in wh_words:
            self.assertNotIn(wh, result, f"WH token {wh!r} should be excluded")
        self.assertIn("예산", result)
        self.assertIn("기관명", result)

    def test_probe11_partial_grounding_passes_after_wh_exclusion(self) -> None:
        """End-to-end: probe_11 scenario resolves with partial_topic_grounding.

        Simulates the exact failure case from real100 eval — retrieval succeeded
        (chunk_recall@10=1.0) but verifier was abstaining due to WH tokens.
        """
        evidence = [
            {
                "doc_id": "20240903676-1.0",
                "chunk_id": "20240903676-1.0::chunk-002",
                "score": 0.8,
                "text": "과업기간 : 착수일로부터 90일 이내",
                "title": (
                    "고양도시관리공사 관산근린공원 다목적구장 "
                    "회원 통합운영관리 시스템 구축"
                ),
                "agency": "고양도시관리공사",
                "project": "",
                "section": "",
            }
        ]
        # Raw topics as analyze_query produces for the probe_11 query
        analysis = {
            "topics": [
                "고양도시관리공사", "다목적구장", "홈페이지",
                "며칠", "안에", "마무리돼",
            ]
        }
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertTrue(
            verified,
            f"probe_11 should pass partial_topic_grounding after WH exclusion; reasons={reasons}",
        )
        self.assertIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)
        self.assertNotIn("topic_not_grounded", reasons)


class CrossEntityContaminationGuardTest(unittest.TestCase):
    """Regression guards for issue #687 — cross-entity incidental matches.

    When the relaxed retrieval stage drops all metadata filters, documents
    from unrelated agencies can be retrieved.  If those documents happen to
    contain 2+ verification topics (e.g. a generic "납품 일정" mention),
    ``partial_topic_grounding`` must NOT be triggered — the evidence is
    entirely from the wrong entity.

    The guard fires only when ``analysis["matched_doc_ids"]`` is non-empty
    (i.e., the query was mapped to specific documents by the analysis layer).
    Queries with no entity constraint leave ``matched_doc_ids`` empty and
    are not affected.
    """

    def _wrong_entity_evidence(self) -> list[dict]:
        """Evidence whose doc_id does NOT match the analysis's matched_doc_ids."""
        return [
            {
                "doc_id": "rfp-agency-g-traffic-hwp",
                "chunk_id": "rfp-agency-g-traffic-hwp::chunk-005",
                "score": 0.40,
                "text": "기관 G의 납품 일정은 착수 후 2개월 이내 설계서 제출, 4개월 이내 장비 설치 완료.",
                "agency": "기관 G",
            },
            {
                "doc_id": "rfp-agency-f-smart-factory-hwp",
                "chunk_id": "rfp-agency-f-smart-factory-hwp::chunk-001",
                "score": 0.39,
                "text": "기관 F는 제조 현장의 생산 실적, 설비 가동률을 통합 관리하는 플랫폼을 구축하고자 한다.",
                "agency": "기관 F",
            },
        ]

    def test_cross_entity_evidence_rejected_when_matched_doc_ids_set(self) -> None:
        """Evidence from wrong agencies must not trigger partial_topic_grounding.

        Simulates the probe for "기관 A의 블록체인 납품 실적은?" after relaxed
        retrieval returned 기관 G (납품) + 기관 F (실적) chunks.  With
        matched_doc_ids=['rfp-agency-a-ai-quality'], the guard detects that no
        evidence doc_id overlaps and rejects partial_topic_grounding.
        """
        analysis = {
            "topics": ["블록체인", "납품", "실적"],
            "matched_doc_ids": ["rfp-agency-a-ai-quality"],
            "entities": ["기관 A"],
        }
        evidence = self._wrong_entity_evidence()
        # 2/3 topics match (납품 + 실적) — fraction 0.67 ≥ 0.5, count 2 ≥ 2.
        # Without the guard this would trigger partial_topic_grounding.
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertFalse(verified, f"cross-entity evidence must not verify; reasons={reasons}")
        self.assertIn("topic_not_grounded", reasons)
        self.assertNotIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)

    def test_cross_entity_guard_inactive_when_no_matched_doc_ids(self) -> None:
        """Guard must be dormant for queries with no entity constraint.

        If ``matched_doc_ids`` is empty (general / out-of-corpus query),
        the guard must not block partial_topic_grounding — it would have no
        sensible target to compare against and would silently break the
        normal partial-topic recovery path.
        """
        analysis = {
            "topics": ["보안 통제", "로그 추적", "감사 로그", "양자암호"],
            # No matched_doc_ids — unconstrained query.
        }
        evidence = [
            {
                "doc_id": "doc-x",
                "chunk_id": "c1",
                "score": 0.5,
                "text": "이 문서는 보안 통제와 로그 추적, 그리고 감사 로그를 다룬다.",
            }
        ]
        # 3/4 topics matched → should still accept (guard inactive).
        verified, reasons = verify_evidence(
            analysis, evidence, allow_partial_topic=True
        )
        self.assertTrue(verified, f"no matched_doc_ids → guard inactive; reasons={reasons}")
        self.assertIn(PARTIAL_TOPIC_GROUNDING_REASON, reasons)


if __name__ == "__main__":
    unittest.main()
