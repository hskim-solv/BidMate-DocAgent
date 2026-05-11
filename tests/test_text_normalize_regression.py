"""Regression guards for the Korean money/date text normalizer (issue #170).

Korean RFP documents (나라장터) express the same value in multiple scripts
within one document — `1,500,000,000` / `15억` / `일금일십오억원정` /
`壹拾伍億元` may all refer to the same amount. The naive substring match in
`rag_core.verify_evidence` cannot bridge these forms.

`text_normalize.normalize_text` (called at query-rewrite and verification
time) is the additive bridge: callers OR-match `expand_forms(topic)` against
both raw and canonical evidence text, so every legacy match still works.

Tests cover four layers:
* `parse_amounts` / `parse_dates` direct parsing (case tables).
* False-positive guard: `반올림`, time, percent, year-alone do not match.
* OR-match additive property: legacy substring matches are preserved.
* End-to-end: `analyze_query` topics include canonical form;
  `verify_evidence` matches across asymmetric query/evidence directions.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from text_normalize import (  # noqa: E402
    expand_forms,
    normalize_text,
    parse_amounts,
    parse_dates,
)
from rag_core import (  # noqa: E402
    analyze_query,
    evidence_has_topic,
    verify_evidence,
)


# ── Direct parser tests ─────────────────────────────────────────────────────

class NormalizeMoneyTest(unittest.TestCase):
    """Case table for ``parse_amounts``. Values are integer KRW."""

    CASES: list[tuple[str, int, bool]] = [
        # (input, expected value, approximate?)
        ("일금일억오천만원정", 150_000_000, False),
        ("일금일억정", 100_000_000, False),
        ("1억 5천만원", 150_000_000, False),
        ("15억원", 1_500_000_000, False),
        ("5천만원", 50_000_000, False),
        ("약 5천만원", 50_000_000, True),
        ("대략 1억", 100_000_000, True),
        ("~3천만원", 30_000_000, True),
        ("90,000,000원", 90_000_000, False),
        ("90,000,000", 90_000_000, False),
        ("壹拾億元", 1_000_000_000, False),
        ("壹億伍仟萬元", 150_000_000, False),
        ("5천만정도", 50_000_000, True),
        ("5천만원 내외", 50_000_000, True),
    ]

    def test_amounts_match_canonical_table(self) -> None:
        for raw, value, approximate in self.CASES:
            with self.subTest(raw=raw):
                results = parse_amounts(raw)
                self.assertEqual(
                    1,
                    len(results),
                    f"expected exactly one match for {raw!r}, got {results}",
                )
                parsed = results[0]
                self.assertEqual(value, parsed.value)
                self.assertEqual(approximate, parsed.approximate)

    def test_multiple_amounts_in_one_string(self) -> None:
        results = parse_amounts("기관 A 예산 5천만원, 기관 B 예산 1억")
        self.assertEqual(2, len(results))
        self.assertEqual([50_000_000, 100_000_000], [r.value for r in results])


class NormalizeDateTest(unittest.TestCase):
    """Case table for ``parse_dates``."""

    CASES: list[tuple[str, str, bool]] = [
        # (input, expected iso, year_inferred?)
        ("2026-03-15", "2026-03-15", False),
        ("2026.03.15", "2026-03-15", False),
        ("2026.3.15", "2026-03-15", False),
        ("'26.3.15.", "2026-03-15", True),
        ("2026년 3월 15일", "2026-03-15", False),
        ("'99.12.31.", "1999-12-31", True),
        ("'30.1.1.", "2030-01-01", True),
        ("'40.1.1.", "1940-01-01", True),
    ]
    ANCHOR_YEAR = 2026

    def test_dates_match_canonical_table(self) -> None:
        for raw, iso, inferred in self.CASES:
            with self.subTest(raw=raw):
                results = parse_dates(raw, anchor_year=self.ANCHOR_YEAR)
                self.assertEqual(1, len(results), f"expected one match for {raw!r}")
                parsed = results[0]
                self.assertEqual(iso, parsed.iso)
                self.assertEqual(inferred, parsed.year_inferred)

    def test_yearless_md_skipped_without_anchor(self) -> None:
        results = parse_dates("3월 15일", anchor_year=None)
        self.assertEqual(1, len(results))
        self.assertEqual("", results[0].iso)
        self.assertTrue(results[0].year_inferred)

    def test_yearless_md_uses_anchor_year(self) -> None:
        results = parse_dates("3월 15일", anchor_year=2026)
        self.assertEqual(1, len(results))
        self.assertEqual("2026-03-15", results[0].iso)
        self.assertTrue(results[0].year_inferred)

    def test_invalid_month_or_day_skipped(self) -> None:
        # Month 13 and day 32 are invalid — silently dropped, no exception.
        self.assertEqual([], parse_dates("2026-13-01"))
        self.assertEqual([], parse_dates("2026-03-32"))


# ── False-positive guards ───────────────────────────────────────────────────

class FalsePositiveGuardTest(unittest.TestCase):
    """Pin the cases where the normalizer must NOT fire."""

    AMOUNT_NEGATIVES = [
        "반올림",
        "반올림한 결과",
        "100% 비율",
        "데이터 3건",
        "오전 10시",
        "2024년",  # year alone is not money
        "약 30%",  # percent, not amount
    ]

    DATE_NEGATIVES = [
        "2024년 예산",  # year-only, no MD
        "10시 30분",  # time, not date
        "전화 02-1234-5678",  # phone number
    ]

    def test_amount_negatives_do_not_match(self) -> None:
        for raw in self.AMOUNT_NEGATIVES:
            with self.subTest(raw=raw):
                self.assertEqual([], parse_amounts(raw))

    def test_date_negatives_do_not_match(self) -> None:
        for raw in self.DATE_NEGATIVES:
            with self.subTest(raw=raw):
                # Allow an empty list OR matches with iso="" (yearless 분 etc.).
                dates = parse_dates(raw)
                self.assertTrue(
                    all(d.iso == "" for d in dates),
                    f"unexpected canonical date for {raw!r}: {dates}",
                )


# ── Additive OR-match property ──────────────────────────────────────────────

class OrMatchAdditiveTest(unittest.TestCase):
    """The new OR-match must preserve every legacy substring match.

    By construction: ``expand_forms(s)`` always includes ``s`` itself, and
    the disjunction tests ``form in text`` as one branch. So if legacy
    ``topic.lower() in evidence_text`` was True, the new check is also True.

    This test pins that property over a sampled fixture so a future refactor
    that drops ``s`` from ``expand_forms`` fails loudly.
    """

    FIXTURE = [
        # (topic, evidence_text) pairs where legacy match is True.
        ("예산", "기관 A의 예산은 5천만원이다."),
        ("ai", "AI 보안 통제 요구사항."),
        ("5천만원", "예산 5천만원, 발주기관 기관 A."),
        ("agency", "agency: 기관 B"),
        ("2026", "마감일 2026-03-15"),
    ]

    def _legacy_matches(self, topic: str, text: str) -> bool:
        return topic.lower() in text.lower()

    def _or_match(self, topic: str, text: str) -> bool:
        text_l = text.lower()
        text_c = normalize_text(text_l)
        return any(
            (form in text_l) or (form in text_c)
            for form in expand_forms(topic.lower())
        )

    def test_legacy_matches_preserved(self) -> None:
        for topic, text in self.FIXTURE:
            with self.subTest(topic=topic, text=text):
                self.assertTrue(self._legacy_matches(topic, text))
                self.assertTrue(self._or_match(topic, text))

    def test_expand_forms_contains_original(self) -> None:
        for s in ("5천만원", "기관 A", "예산", ""):
            with self.subTest(s=s):
                self.assertIn(s, expand_forms(s))


# ── End-to-end through rag_core hooks ───────────────────────────────────────

def _evidence_item(text: str, agency: str = "기관 A") -> dict:
    return {
        "text": text,
        "title": "Test",
        "agency": agency,
        "doc_id": "test-doc",
        "chunk_id": "test-doc#0",
        "metadata": {"agency": agency, "doc_id": "test-doc"},
        "score": 0.9,
    }


class EndToEndAnalyzeQueryTest(unittest.TestCase):
    """``analyze_query`` must surface canonical-form tokens."""

    def test_korean_money_query_includes_canonical_topic(self) -> None:
        result = analyze_query("기관 A의 예산 5천만원 차이", [])
        self.assertIn("50000000", result["topics"])

    def test_korean_date_query_includes_canonical_topic(self) -> None:
        # The canonical date "2026-03-15" gets tokenized by TOKEN_RE into
        # ["2026", "03", "15"]; the zero-padded "03" is the proof that the
        # canonical form was tokenized in (the raw "3월 15일" has no "03").
        result = analyze_query("기관 A의 2026년 3월 15일 일정", [])
        self.assertIn("03", result["topics"], f"topics={result['topics']}")

    def test_query_without_money_or_date_unaffected(self) -> None:
        result = analyze_query("기관 A의 보안 통제 요구사항", [])
        # No canonical-form tokens should be injected.
        self.assertFalse(
            any(re_digit(t) and t.isdigit() and len(t) > 6 for t in result["topics"]),
            f"unexpected numeric topic in plain query: {result['topics']}",
        )


def re_digit(s: str) -> bool:
    return any(c.isdigit() for c in s)


class EndToEndVerifyEvidenceTest(unittest.TestCase):
    """``verify_evidence`` must OR-match across query/evidence script forms.

    Asymmetry surfaces are the issue #170 regression target: today's
    substring-only verifier fails when query and evidence use different forms
    for the same amount.
    """

    def _analysis(self, topics: list[str], query_type: str = "single_doc") -> dict:
        return {
            "query_type": query_type,
            "topics": topics,
            "entities": [],
            "matched_doc_ids": [],
            "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
        }

    def test_query_canonical_matches_korean_evidence(self) -> None:
        # Query topic "50000000" must match evidence "5천만원" via OR-match.
        evidence = [_evidence_item("기관 A 예산은 5천만원이다.")]
        verified, reasons = verify_evidence(self._analysis(["50000000"]), evidence)
        self.assertTrue(verified, f"expected verified, got reasons={reasons}")

    def test_query_korean_matches_canonical_evidence(self) -> None:
        # Query topic "5천만원" must match evidence "50,000,000원" via OR-match.
        evidence = [_evidence_item("기관 B 예산 50,000,000원")]
        verified, reasons = verify_evidence(self._analysis(["5천만원"]), evidence)
        self.assertTrue(verified, f"expected verified, got reasons={reasons}")

    def test_evidence_has_topic_or_matches_both_directions(self) -> None:
        item_korean = _evidence_item("기관 A 예산은 5천만원이다.")
        item_canonical = _evidence_item("기관 B 예산 50,000,000원")
        # canonical query topic matches korean evidence
        self.assertTrue(evidence_has_topic(item_korean, ["50000000"]))
        # korean query topic matches canonical evidence
        self.assertTrue(evidence_has_topic(item_canonical, ["5천만원"]))

    def test_unrelated_topic_still_does_not_match(self) -> None:
        # OR-match additivity must not cause false positives — unrelated
        # topics must NOT match.
        item = _evidence_item("기관 A 예산은 5천만원이다.")
        self.assertFalse(evidence_has_topic(item, ["완전히다른토픽xyz"]))

    def test_canonical_iso_date_matches_korean_date_evidence(self) -> None:
        # Query topic "2026-03-15" (canonical) must match evidence written
        # as "2026년 3월 15일" via the canonical-form OR-match.
        item = _evidence_item("기관 A 마감일 2026년 3월 15일.")
        self.assertTrue(evidence_has_topic(item, ["2026-03-15"]))


if __name__ == "__main__":
    unittest.main()
