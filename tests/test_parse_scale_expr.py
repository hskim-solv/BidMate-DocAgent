"""Unit coverage for ``rag_normalize._parse_scale_expr``.

한국어 금액/수량 스케일 표현을 계층적으로 파싱하는 순수 함수다 (천/백/십 은
직전 선행 숫자를 section 누적기에 곱하고, 만/억/조 는 section 을 running total
로 flush). RFP 숫자 정규화 경로의 핵심이라 누적 규칙·None 경로가 회귀하면 금액
추출이 조용히 틀어진다. 직접 단위 테스트가 없어 다음을 oracle 로 고정한다:

- sino/numeric 숫자 합성, 콤마 strip, decimal 처리
- small/big scale 의 bare(선행 숫자 없는) 기본값과 section flush 순서
- segment-0 → 1 guard ('0만', bare '만')
- 무진행/미인식/InvalidOperation/total-0 의 None 경로
- 반환 타입(Decimal)

모든 기대값은 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rag_normalize import _parse_scale_expr


# (입력, 기대 정수값) — Decimal == int 비교가 성립한다.
VALUE_CASES = [
    ("5천만", 50_000_000),          # docstring 예시: 5 ×천 → 5000 ×만 → 5천만
    ("1억", 100_000_000),
    ("삼천만", 30_000_000),          # sino 3 ×천 ×만
    ("오천", 5_000),
    ("1,000", 1_000),               # numeric 콤마 strip
    ("12345", 12_345),              # plain number
    ("십", 10),                      # bare small scale → pending None → 1×10
    ("백", 100),
    ("천", 1_000),
    ("만", 10_000),                  # bare big scale → segment 0 → 1 ×만
    ("억", 100_000_000),
    ("조", 1_000_000_000_000),
    ("0만", 10_000),                 # 선행 0 이어도 segment 0 → 1 guard 로 1만
    ("백만", 1_000_000),             # 100 ×만
    ("천만", 10_000_000),            # bare small(천=1000) → big(만) 합성
    ("2천5백", 2_500),               # 한 section 안 다중 small scale
    ("삼천오백", 3_500),
    ("1억 2천만", 120_000_000),      # 공백 구분 + section flush
    ("삼억오천만", 350_000_000),
    ("1조2345억", 1_234_500_000_000),  # big + big
    ("2억3천4백5십6", 200_003_456),    # 전체 합성
    ("  5천  ", 5_000),              # 외곽 공백 허용
    ("1.5억", 150_000_000),          # decimal 숫자
]

NONE_CASES = [
    "",          # 빈 문자열 → 무진행
    "   ",       # 공백뿐 → 무진행
    "abc",       # 미인식 토큰
    "0",         # total 0 → >0 아님
    "공",         # sino 0 → total 0
    "1.2.3억",   # Decimal InvalidOperation
    "5천만원",   # 미인식 trailing('원') → 전체 파싱 실패
]


@pytest.mark.parametrize("text, expected", VALUE_CASES)
def test_parse_scale_expr_values(text: str, expected: int) -> None:
    assert _parse_scale_expr(text) == Decimal(expected)


@pytest.mark.parametrize("text", NONE_CASES)
def test_parse_scale_expr_returns_none(text: str) -> None:
    assert _parse_scale_expr(text) is None


def test_bare_big_scale_segment_zero_promoted_to_one() -> None:
    # 선행 숫자 없는 big scale 은 segment 를 1 로 승격해 단위값 그대로 반환한다.
    # ('만' → 0 이 아니라 10_000) — segment-0 guard 가 사라지면 0(=>None)으로 무너진다.
    assert _parse_scale_expr("만") == Decimal(10_000)
    assert _parse_scale_expr("0만") == Decimal(10_000)


def test_bare_small_scale_uses_implicit_leading_one() -> None:
    # 선행 숫자 없는 small scale 은 pending 1 로 곱한다('천' → 0 이 아니라 1000).
    assert _parse_scale_expr("천") == Decimal(1_000)


def test_trailing_unrecognized_token_aborts_whole_expression() -> None:
    # 부분 누적이 있어도 미인식 토큰을 만나면 전체가 None — 부분값을 반환하지 않는다.
    assert _parse_scale_expr("5천만원") is None


def test_return_type_is_decimal() -> None:
    result = _parse_scale_expr("5천만")
    assert isinstance(result, Decimal)


def test_section_flush_does_not_double_count_across_big_scale() -> None:
    # '1억 2천만' = 1억(flush) + 2천만 → 120_000_000. flush 후 section 이 리셋되지
    # 않으면 더 큰 값으로 새므로 정확한 합을 pin 한다.
    assert _parse_scale_expr("1억 2천만") == Decimal(120_000_000)
