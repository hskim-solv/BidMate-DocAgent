"""Regression tests for aggregate-query evidence pool expansion (issue #675).

Context
-------
``select_supporting_evidence`` previously used a hard ``pool[:2]`` ceiling
for all non-comparison queries.  In ``probe_12_citation_kosaf_aggregate``
the gold chunk (rank 5, containing "사업기간: 계약일로부터 6개월") was
always cut off, causing accuracy=0 even though chunk_recall@10=1.0.

Fix: detect aggregate-intent tokens ("모든", "전체", "정리", …) in the
resolved query / token list and widen the pool to ``_AGGREGATE_POOL_MAX``
(currently 5).

These tests verify:

1. Non-aggregate queries preserve the existing pool[:2] behaviour.
2. Aggregate queries widen to pool[:_AGGREGATE_POOL_MAX].
3. The pool is clamped to the actual evidence length (no padding).
4. Comparison-query logic is unchanged.
5. Probe-12 regression: gold chunk at rank 5 appears in the result.
"""

from __future__ import annotations

import unittest

from rag_answer import (
    _AGGREGATE_POOL_MAX,
    _AGGREGATE_SIGNALS,
    _is_aggregate_query,
    select_supporting_evidence,
)
from rag_query import analyze_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _analysis(
    *,
    query_type: str = "single_doc",
    resolved_query: str = "",
    tokens: list[str] | None = None,
    entities: list[str] | None = None,
) -> dict:
    return {
        "query_type": query_type,
        "resolved_query": resolved_query,
        "tokens": tokens or [],
        "entities": entities or [],
    }


def _ev(chunk_id: str, text: str = "일정 금액 기간", agency: str = "기관A") -> dict:
    return {"chunk_id": chunk_id, "text": text, "agency": agency}


def _ev_list(n: int, *, text: str = "일정 금액") -> list[dict]:
    return [_ev(f"doc::chunk-{i:03d}", text=text) for i in range(n)]


# ---------------------------------------------------------------------------
# _is_aggregate_query unit tests
# ---------------------------------------------------------------------------

class TestIsAggregateQuery(unittest.TestCase):

    def test_plain_query_returns_false(self) -> None:
        a = _analysis(resolved_query="사업 예산은?", tokens=["사업", "예산"])
        self.assertFalse(_is_aggregate_query(a))

    def test_모든_in_resolved_query(self) -> None:
        a = _analysis(resolved_query="모든 일정과 금액 정리해줘", tokens=["일정", "금액"])
        self.assertTrue(_is_aggregate_query(a))

    def test_전체_in_tokens(self) -> None:
        a = _analysis(resolved_query="일정과 금액", tokens=["전체", "일정", "금액"])
        self.assertTrue(_is_aggregate_query(a))

    def test_정리_in_resolved_query(self) -> None:
        a = _analysis(resolved_query="일정 정리해줘", tokens=["일정"])
        self.assertTrue(_is_aggregate_query(a))

    def test_모두_in_tokens(self) -> None:
        a = _analysis(resolved_query="항목", tokens=["모두", "항목"])
        self.assertTrue(_is_aggregate_query(a))

    def test_empty_analysis_returns_false(self) -> None:
        self.assertFalse(_is_aggregate_query({}))

    def test_all_declared_signals_trigger(self) -> None:
        """Every token in _AGGREGATE_SIGNALS must fire the flag."""
        for sig in _AGGREGATE_SIGNALS:
            with self.subTest(signal=sig):
                self.assertTrue(
                    _is_aggregate_query(_analysis(resolved_query=f"x {sig} y")),
                    f"signal '{sig}' did not trigger aggregate detection",
                )

    # --- issue #2179: substring-fallback compound-noun guard ----------------
    # A signal fused with a nominalizer suffix (성/화/율/률/형) is a compound
    # noun (전체성/목록화/정리율/일체형), not aggregate intent. A signal merged
    # into a token but followed by a compound part / verb ending / space
    # (전체일정/전부다/정리해줘) stays aggregate, preserving #2170 recall.
    _COMPOUND_FALSE_POSITIVES = [
        "전체성", "목록화", "정리율", "일체형",
        "전체성 평가", "목록화 작업", "정리율 산정",
    ]
    _MERGED_TOKEN_AGGREGATES = [
        "전체일정", "전부다", "모두다", "전체다", "정리해줘",
        "나열해줘", "목록작성", "모든일정", "전부보여줘",
    ]

    def test_compound_noun_not_aggregate(self) -> None:
        # tokens=[q] models the merged compound so only the substring fallback
        # can fire; the nominalizer suffix must guard it out.
        for q in self._COMPOUND_FALSE_POSITIVES:
            with self.subTest(q=q):
                a = _analysis(resolved_query=q, tokens=[q])
                self.assertFalse(
                    _is_aggregate_query(a), f"{q!r} should not be aggregate (#2179)"
                )

    def test_merged_token_aggregate_still_detected(self) -> None:
        # #2170 recall: a real aggregate merged into one token (no exact match)
        # must still fire via the substring fallback — the char after the signal
        # is a compound part / verb ending, not a nominalizer.
        for q in self._MERGED_TOKEN_AGGREGATES:
            with self.subTest(q=q):
                a = _analysis(resolved_query=q, tokens=[q])
                self.assertTrue(
                    _is_aggregate_query(a), f"{q!r} should stay aggregate (#2170)"
                )

    _VERBALIZED_AGGREGATES = [
        "목록화해줘", "목록화해", "목록화하라", "목록화함",
        "전체화해줘", "정리화하여", "목록화했다",
    ]

    def test_verbalized_nominalizer_still_aggregate(self) -> None:
        # Codex review (#2179): a nominalizer suffix re-verbed by 하다 (목록화해줘)
        # is a listing request, not a bare noun — it must stay aggregate while the
        # bare nominal (목록화) is still guarded out by test_compound_noun_not_aggregate.
        for q in self._VERBALIZED_AGGREGATES:
            with self.subTest(q=q):
                a = _analysis(resolved_query=q, tokens=[q])
                self.assertTrue(
                    _is_aggregate_query(a),
                    f"{q!r} should stay aggregate (#2179 verbalized nominalizer)",
                )

    _SUFFIX_COMPOUND_NEGATIVES = [
        "일체형하우징", "정리형하중", "전체형하부", "정리율하한", "전체성하부구조",
    ]

    def test_non_hwa_suffix_plus_ha_not_aggregate(self) -> None:
        # Codex review (#2179): only ~화 takes 하다; 형/율/률/성 + 하 is an accidental
        # compound (일체형하우징/정리형하중), not a verbalized aggregate. The verbalizer
        # exception must stay scoped to the 화 suffix.
        for q in self._SUFFIX_COMPOUND_NEGATIVES:
            with self.subTest(q=q):
                a = _analysis(resolved_query=q, tokens=[q])
                self.assertFalse(
                    _is_aggregate_query(a),
                    f"{q!r} should not be aggregate (#2179 non-화 suffix)",
                )

    def test_exact_token_overrides_compound_suffix(self) -> None:
        # An exact token signal wins even when resolved also carries a compound.
        a = _analysis(resolved_query="전체성 분석", tokens=["전체", "분석"])
        self.assertTrue(_is_aggregate_query(a))

    def test_signal_at_string_end_is_aggregate(self) -> None:
        # signal with nothing after it (string end, not a suffix) → aggregate.
        a = _analysis(resolved_query="예산 전체", tokens=["예산전체"])
        self.assertTrue(_is_aggregate_query(a))


# ---------------------------------------------------------------------------
# select_supporting_evidence pool-size tests
# ---------------------------------------------------------------------------

class TestSelectSupportingEvidencePoolSize(unittest.TestCase):

    def test_non_aggregate_caps_at_2(self) -> None:
        ev = _ev_list(6)
        a = _analysis(resolved_query="사업 예산은?", tokens=["사업", "예산"])
        result = select_supporting_evidence(a, ev)
        self.assertLessEqual(len(result), 2)

    def test_aggregate_widens_to_pool_max(self) -> None:
        ev = _ev_list(_AGGREGATE_POOL_MAX + 3)
        a = _analysis(
            resolved_query="모든 일정과 금액 정리해줘",
            tokens=["모든", "일정", "금액"],
        )
        result = select_supporting_evidence(a, ev)
        self.assertEqual(len(result), _AGGREGATE_POOL_MAX)

    def test_aggregate_with_fewer_than_max_evidence(self) -> None:
        """Pool clamped to actual evidence count, not padded."""
        ev = _ev_list(3)
        a = _analysis(
            resolved_query="모든 일정과 금액",
            tokens=["모든", "일정", "금액"],
        )
        result = select_supporting_evidence(a, ev)
        self.assertEqual(len(result), 3)

    def test_aggregate_empty_evidence_returns_empty(self) -> None:
        a = _analysis(resolved_query="모든 일정 정리", tokens=["모든", "일정"])
        self.assertEqual(select_supporting_evidence(a, []), [])

    def test_comparison_query_unchanged(self) -> None:
        """Aggregate token in comparison query must not override entity-matching logic."""
        ev = [
            _ev("doc1::chunk-001", agency="기관A"),
            _ev("doc2::chunk-001", agency="기관B"),
        ] + _ev_list(6)
        a = _analysis(
            query_type="comparison",
            resolved_query="기관A와 기관B 모든 예산 비교",
            tokens=["기관A", "기관B", "모든", "예산"],
            entities=["기관A", "기관B"],
        )
        result = select_supporting_evidence(a, ev)
        agencies = [r.get("agency") for r in result]
        self.assertIn("기관A", agencies)
        self.assertIn("기관B", agencies)


# ---------------------------------------------------------------------------
# Probe-12 regression: gold chunk at rank 5 must appear in result
# ---------------------------------------------------------------------------

class TestProbe12AggregateRegression(unittest.TestCase):
    """Regression guard for probe_12_citation_kosaf_aggregate.

    The gold chunk (chunk-004, "사업기간: 계약일로부터 6개월") ranked 5th in
    retrieval.  Before the fix, pool[:2] always excluded it; after the fix,
    aggregate detection widens the pool to 5 so chunk-004 is included.
    """

    _GOLD_CHUNK_ID = "20240815487-0.0::chunk-004"

    def _make_evidence(self) -> list[dict]:
        """Simulate probe_12 retrieval order (rank 1-8)."""
        order = [9, 1, 10, 3, 4, 2, 5, 7]  # rank order from eval_summary
        ev = []
        for i in order:
            cid = f"20240815487-0.0::chunk-{i:03d}"
            if i == 4:
                text = "사업기간: 계약일로부터 6개월 사업금액: 211,000,000원"
            elif i == 9:
                text = "추진 목표 사업 일정 관리 시스템 기능 개선"
            else:
                text = f"청크 {i} 내용"
            ev.append({"chunk_id": cid, "text": text, "agency": "한국사학진흥재단"})
        return ev

    def test_gold_chunk_excluded_without_aggregate_signal(self) -> None:
        """Sanity-check: without aggregate signal, pool[:2] cuts chunk-004 (rank 5)."""
        ev = self._make_evidence()
        a = _analysis(
            resolved_query="한국사학진흥재단 대학재정정보시스템 사업의 일정과 금액",
            tokens=["한국사학진흥재단", "대학재정정보시스템", "일정", "금액"],
        )
        result = select_supporting_evidence(a, ev)
        chunk_ids = [r["chunk_id"] for r in result]
        self.assertNotIn(self._GOLD_CHUNK_ID, chunk_ids)

    def test_gold_chunk_included_with_aggregate_signal(self) -> None:
        """Fix: "모든" triggers wide pool → chunk-004 at rank 5 is included."""
        ev = self._make_evidence()
        a = _analysis(
            resolved_query="한국사학진흥재단 대학재정정보시스템 사업의 모든 일정과 금액 정리해줘",
            tokens=["한국사학진흥재단", "대학재정정보시스템", "모든", "일정", "금액"],
        )
        result = select_supporting_evidence(a, ev)
        chunk_ids = [r["chunk_id"] for r in result]
        self.assertIn(self._GOLD_CHUNK_ID, chunk_ids)


# ---------------------------------------------------------------------------
# analyze_query end-to-end integration: guards the #2170 test-reality drift
# ---------------------------------------------------------------------------

class TestAnalyzeQueryAggregateIntegration(unittest.TestCase):
    """End-to-end: the *real* analyze_query output must drive _is_aggregate_query.

    The pool-size tests above build the analysis dict via the ``_analysis``
    helper, which injects a ``resolved_query`` key.  Runtime ``analyze_query``
    previously omitted that key, so ``_is_aggregate_query``'s substring fallback
    was dead in production while these unit tests stayed green — a mock-vs-
    reality drift (#2170).  These tests call ``analyze_query`` directly so the
    key contract is pinned end-to-end.
    """

    def test_analyze_query_exposes_resolved_query(self) -> None:
        analysis = analyze_query("전체일정 알려줘", [])
        self.assertIn("resolved_query", analysis)

    def test_compound_token_aggregate_detected_end_to_end(self) -> None:
        # tokenize("전체일정 알려줘") == ["전체일정"]: the bare signal "전체" is
        # merged into a compound token, so token matching alone cannot fire.
        # The substring fallback over resolved_query must still flag aggregate.
        analysis = analyze_query("전체일정 알려줘", [])
        self.assertNotIn("전체", analysis["tokens"])  # precondition: token path blind
        self.assertTrue(_is_aggregate_query(analysis))

    def test_plain_query_not_flagged_end_to_end(self) -> None:
        analysis = analyze_query("사업 예산은 얼마인가", [])
        self.assertFalse(_is_aggregate_query(analysis))

    def test_compound_noun_not_flagged_end_to_end(self) -> None:
        # issue #2179: tokenize("전체성을 평가한다") merges "전체성" into one token,
        # so the token path is blind; the substring fallback must NOT fire on the
        # compound noun (전체 + 성 nominalizer). The precision-direction mirror of
        # the #2170 recall drift guard above.
        analysis = analyze_query("전체성을 평가한다", [])
        self.assertNotIn("전체", analysis["tokens"])  # precondition: token path blind
        self.assertFalse(_is_aggregate_query(analysis))


if __name__ == "__main__":
    unittest.main()
