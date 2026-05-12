"""Regression guard for bidmate_security.redact_pii (issue #455, ADR 0028).

Korean phone / email / RRN patterns. The function is idempotent: the
replacement tokens contain no characters matched by any pattern, so
re-applying it yields the same result.
"""

from __future__ import annotations

import unittest

from bidmate_security import redact_pii


class RedactPhoneTest(unittest.TestCase):

    CASES = (
        # (input, expected)
        ("문의: 010-1234-5678", "문의: <phone>"),
        ("연락처 01012345678", "연락처 <phone>"),
        ("담당자 010 1234 5678 전화", "담당자 <phone> 전화"),
        ("011-234-5678", "<phone>"),  # legacy 3-digit middle
        ("016-9876-5432", "<phone>"),
        ("017-1234-5678", "<phone>"),
        ("018-1234-5678", "<phone>"),
        ("019-1234-5678", "<phone>"),
        # Non-matches must pass through unchanged.
        ("일반 번호 02-1234-5678", "일반 번호 02-1234-5678"),  # 02 prefix
        ("계좌 1234567890123456", "계좌 1234567890123456"),
        # 14자리는 매치되지 않아야 함 (Korean mobile is 11 digits max)
        ("01012345678901", "01012345678901"),
    )

    def test_phone_patterns(self) -> None:
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(redact_pii(raw), expected)


class RedactEmailTest(unittest.TestCase):

    CASES = (
        ("이메일 foo@bar.com 으로 문의", "이메일 <email> 으로 문의"),
        ("user.name+tag@example.co.kr", "<email>"),
        ("multi: a@b.com, c@d.org", "multi: <email>, <email>"),
        # Non-matches.
        ("@not-an-email", "@not-an-email"),
        ("plain text without email", "plain text without email"),
    )

    def test_email_patterns(self) -> None:
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(redact_pii(raw), expected)


class RedactRRNTest(unittest.TestCase):

    CASES = (
        ("주민: 900101-1234567", "주민: <rrn>"),
        ("9001011234567", "<rrn>"),  # no dash
        ("주민 900101 1234567", "주민 <rrn>"),  # space separator
        ("000101-3000000", "<rrn>"),  # century marker 3 (2000s, male)
        ("000101-4000000", "<rrn>"),  # century marker 4 (2000s, female)
        # Non-matches: wrong digit count or invalid sex marker.
        ("9001015000000", "9001015000000"),  # marker 5 not in [1-4]
        ("90010112345", "90010112345"),  # too short
    )

    def test_rrn_patterns(self) -> None:
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(redact_pii(raw), expected)


class RedactCombinedTest(unittest.TestCase):

    def test_all_three_in_one_paragraph(self) -> None:
        raw = (
            "담당자 김아무개 010-1234-5678, 이메일 kim@acme.co.kr, "
            "주민 900101-1234567 으로 등록"
        )
        out = redact_pii(raw)
        self.assertIn("<phone>", out)
        self.assertIn("<email>", out)
        self.assertIn("<rrn>", out)
        # Original PII gone.
        self.assertNotIn("010-1234-5678", out)
        self.assertNotIn("kim@acme.co.kr", out)
        self.assertNotIn("900101-1234567", out)


class RedactIdempotencyTest(unittest.TestCase):

    def test_redact_is_idempotent(self) -> None:
        raw = "010-1234-5678 / foo@bar.com / 900101-1234567"
        once = redact_pii(raw)
        twice = redact_pii(once)
        self.assertEqual(once, twice)

    def test_empty_string_pass_through(self) -> None:
        self.assertEqual(redact_pii(""), "")

    def test_plain_text_unchanged(self) -> None:
        raw = "본 사업은 인공지능 기반 문서 분석 시스템 구축을 목적으로 한다"
        self.assertEqual(redact_pii(raw), raw)


if __name__ == "__main__":
    unittest.main()
