"""Unit coverage for text_normalize.py 금액/날짜 파싱 internal helper (issue #2291).

대상 6종은 모두 순수(import 시 torch/chromadb/rag_core 미로드)인데 직접 단위
테스트가 0건이라 RFP 예산·기한 추출 정확도를 떠받치는 파싱 로직이 조용히
깨질 수 있었다(test-only, 소스 무수정):

- ``_parse_korean_number`` — 만/억/조 단위·복합·콤마 무시; envelope-only/불량
  문자 → None (regex 후 false-positive 2차 가드)
- ``_resolve_year`` — 2자리 → 4자리 sliding window
- ``_valid_md`` — 월/일 경계
- ``_spans_overlap`` — 반열린 구간 겹침(인접 non-overlap)
- ``_is_approximate`` — 근사 표현 prefix(약/대략/~)·suffix(정도/내외) 탐지
- ``_strip_envelopes`` — envelope(일금/정/원/元/圓)·공백·콤마 제거

negative assertion 으로 단위 누적·연도 경계·구간 인접·envelope-only None 을
못 박는다.
"""
from __future__ import annotations

import datetime

from text_normalize import (
    _is_approximate,
    _parse_korean_number,
    _resolve_year,
    _spans_overlap,
    _strip_envelopes,
    _valid_md,
)


# ---- _parse_korean_number ----

def test_parse_arabic_with_comma() -> None:
    assert _parse_korean_number("1000") == 1000
    assert _parse_korean_number("1,000") == 1000  # 콤마는 무시


def test_parse_korean_unit_scales() -> None:
    assert _parse_korean_number("12만") == 120_000
    assert _parse_korean_number("3억") == 300_000_000
    assert _parse_korean_number("2조") == 2_000_000_000_000


def test_parse_compound_units_accumulate() -> None:
    # 복합 단위는 누적 합산(곱셈/덮어쓰기 mutant KILL).
    assert _parse_korean_number("3억5천만") == 350_000_000
    assert _parse_korean_number("1억2000만") == 120_000_000
    assert _parse_korean_number("천만") == 10_000_000  # 천만 = 1000만
    # 동일 section 내 subunit 다중 누적(천+백): 덮어쓰기 mutant 면 5_000_000 오답.
    assert _parse_korean_number("1천5백만") == 15_000_000


def test_parse_rejects_envelope_only_and_garbage() -> None:
    # 2차 false-positive 가드: 값이 없거나 알 수 없는 문자가 섞이면 None.
    assert _parse_korean_number("") is None
    assert _parse_korean_number("원") is None  # envelope 만 → 빈 → None
    assert _parse_korean_number("금 5000 원") is None  # '금'은 envelope 아님 → 불량
    assert _parse_korean_number("영") is None  # well-formed 이지만 값 0 → zero-value 가드


# ---- _resolve_year ----

def test_resolve_year_sliding_window_boundary() -> None:
    # anchor 2026 → anchor_yy=26, century=2000. yy ≤ 31(=26+5) 이면 현세기,
    # 초과면 직전 세기. 경계 31/32 에서 2031 vs 1932 로 갈린다.
    assert _resolve_year(26, 2026) == 2026
    assert _resolve_year(31, 2026) == 2031  # 경계 포함
    assert _resolve_year(32, 2026) == 1932  # 경계 초과 → 직전 세기
    assert _resolve_year(99, 2026) == 1999


def test_resolve_year_none_anchor_uses_today() -> None:
    # anchor None → 오늘 연도 기준(전역 상수/0 으로 바뀌면 KILL).
    this_year = datetime.date.today().year
    assert _resolve_year(26, None) == _resolve_year(26, this_year)


# ---- _valid_md ----

def test_valid_md_boundaries() -> None:
    assert _valid_md(1, 1) is True
    assert _valid_md(12, 31) is True
    assert _valid_md(0, 1) is False  # month 하한 밖
    assert _valid_md(13, 1) is False  # month 상한 밖
    assert _valid_md(1, 0) is False  # day 하한 밖
    assert _valid_md(1, 32) is False  # day 상한 밖


# ---- _spans_overlap ----

def test_spans_overlap_half_open() -> None:
    assert _spans_overlap((0, 5), (3, 8)) is True  # 부분 겹침
    assert _spans_overlap((0, 10), (3, 5)) is True  # 포함
    assert _spans_overlap((0, 5), (5, 9)) is False  # 인접(끝==시작) → non-overlap
    assert _spans_overlap((0, 3), (5, 9)) is False  # 분리


# ---- _is_approximate ----

def test_is_approximate_prefix_and_suffix() -> None:
    # prefix: span 앞이 약/대략/~. suffix: span 뒤가 정도/내외.
    assert _is_approximate("약 1000원", (2, 6)) is True  # "약 " prefix
    assert _is_approximate("1000 내외", (0, 4)) is True  # " 내외" suffix
    assert _is_approximate("1000 정도", (0, 4)) is True


def test_is_approximate_false_for_plain_and_unsupported() -> None:
    assert _is_approximate("정확히 1000", (4, 8)) is False  # 근사 표현 없음
    assert _is_approximate("1000가량", (0, 4)) is False  # '가량'은 미지원
    assert _is_approximate("1000 안팎", (0, 4)) is False  # '안팎'은 미지원


# ---- _strip_envelopes ----

def test_strip_envelopes_removes_envelopes_spaces_commas() -> None:
    # '원'/'정' 은 envelope → 제거; 공백·콤마도 제거. '금' 단독은 envelope 아님.
    assert _strip_envelopes("금 1,234 원") == "금1234"
    assert _strip_envelopes("일금 5,000 원정") == "5000"  # 일금/원/정 모두 제거
    assert _strip_envelopes("1, 000") == "1000"
