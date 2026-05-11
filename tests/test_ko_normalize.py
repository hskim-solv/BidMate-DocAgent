"""Table-driven tests for rag_normalize (issue #170).

These exercise the parser surface only — the module is not yet wired
into the rag_core query path, so there are no integration tests here.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from rag_normalize import normalize_currency, normalize_date


class TestNormalizeCurrency(unittest.TestCase):
    def test_pure_digit_forms(self) -> None:
        cases = [
            ("10000000원", Decimal("10000000")),
            ("10,000,000원", Decimal("10000000")),
            ("10,000,000", Decimal("10000000")),
            ("0", Decimal(0)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_currency(text), expected)

    def test_scale_word_forms(self) -> None:
        cases = [
            ("1억원", Decimal("100000000")),
            ("3억원", Decimal("300000000")),
            ("3억5천만원", Decimal("350000000")),
            ("3,500만원", Decimal("35000000")),
            ("5천만원", Decimal("50000000")),
            ("1억 5천만원", Decimal("150000000")),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_currency(text), expected)

    def test_sino_korean_digit_multipliers(self) -> None:
        cases = [
            ("삼억원", Decimal("300000000")),
            ("일금삼억원", Decimal("300000000")),
            ("일금 일억 오천만원", Decimal("150000000")),
            ("이십원", Decimal(20)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_currency(text), expected)

    def test_decimal_scale(self) -> None:
        self.assertEqual(normalize_currency("1.5억원"), Decimal("150000000"))

    def test_rejects_non_currency(self) -> None:
        cases = ["", "   ", "내용 없음", "원", "abc원"]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(normalize_currency(text))


class TestNormalizeDate(unittest.TestCase):
    def test_iso_like_separators(self) -> None:
        cases = [
            ("2026-05-11", date(2026, 5, 11)),
            ("2026/05/11", date(2026, 5, 11)),
            ("2026.5.11", date(2026, 5, 11)),
            ("2026.05.11", date(2026, 5, 11)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_date(text), expected)

    def test_korean_form(self) -> None:
        cases = [
            ("2026년 5월 11일", date(2026, 5, 11)),
            ("2026년 05월 11일", date(2026, 5, 11)),
            ("2026년5월11일", date(2026, 5, 11)),
            ("2026년 5월 11", date(2026, 5, 11)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_date(text), expected)

    def test_two_digit_year_with_apostrophe(self) -> None:
        cases = [
            ("'26.5.11", date(2026, 5, 11)),
            ("‘26.5.11", date(2026, 5, 11)),
            ("'26-05-11", date(2026, 5, 11)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_date(text), expected)

    def test_embedded_in_sentence(self) -> None:
        self.assertEqual(
            normalize_date("제출 기한: 2026년 5월 11일까지"),
            date(2026, 5, 11),
        )
        self.assertEqual(
            normalize_date("계약일은 2026-05-11이다."),
            date(2026, 5, 11),
        )

    def test_rejects_invalid_or_missing(self) -> None:
        cases = ["", "   ", "날짜 없음", "2026-13-11", "2026-05-32"]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(normalize_date(text))

    def test_century_pivot_override(self) -> None:
        self.assertEqual(
            normalize_date("'99.12.31", century_pivot=1900),
            date(1999, 12, 31),
        )


if __name__ == "__main__":
    unittest.main()
