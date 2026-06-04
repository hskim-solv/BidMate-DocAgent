"""Unit coverage for ingestion.py CSV/텍스트/예산 정규화 순수 helper (issue #2323).

``parse_budget`` / ``clean_cell`` / ``normalize_body_text`` / ``slug_part`` /
``normalize_file_format`` 은 import-safe leaf(torch/chromadb/rag_core 미로드)인데
직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``parse_budget`` — comma 제거 후 정수면 int, 소수면 float, 파싱 실패면 원문 문자열,
  None/빈 → None. int/float 타입 구별까지 고정.
- ``slug_part`` — 연속 공백을 하이픈 1개로 collapse(NFC).
- ``normalize_file_format`` — value 가 있으면 우선, 없을 때만 파일명 suffix.
"""
from __future__ import annotations

import unicodedata

from ingestion import (
    clean_cell,
    normalize_body_text,
    normalize_file_format,
    parse_budget,
    slug_part,
)


# ---- parse_budget ----

def test_parse_budget_int_float_text_and_empty() -> None:
    # comma 제거 + 정수 → int (타입까지 구별; float 이면 KILL).
    out_int = parse_budget("1,000")
    assert out_int == 1000 and isinstance(out_int, int)
    # 소수 → float.
    out_float = parse_budget("1,234.5")
    assert out_float == 1234.5 and isinstance(out_float, float)
    # "100.0" 은 is_integer() → int 로 다운캐스트.
    out_round = parse_budget("100.0")
    assert out_round == 100 and isinstance(out_round, int)
    # 숫자가 아니면 원문(clean_cell) 문자열 그대로 반환.
    assert parse_budget("약 5억") == "약 5억"
    # None / 공백 → None.
    assert parse_budget(None) is None
    assert parse_budget("   ") is None


# ---- clean_cell ----

def test_clean_cell_handles_none_and_strips() -> None:
    assert clean_cell(None) == ""  # None → 빈 문자열("None" 아님)
    assert clean_cell("  x  ") == "x"  # 양끝 공백 제거
    assert clean_cell("   ") == ""  # 공백만 → 빈 문자열


# ---- normalize_body_text ----

def test_normalize_body_text_unifies_newlines() -> None:
    # CRLF·CR 모두 LF 로 통일.
    assert normalize_body_text("a\r\nb\rc") == "a\nb\nc"
    assert normalize_body_text(None) == ""


# ---- slug_part ----

def test_slug_part_collapses_whitespace_to_single_hyphen() -> None:
    # 연속 공백(스페이스/탭) → 하이픈 1개. "가--나" 같은 다중 하이픈이면 KILL.
    assert slug_part("가  나   다") == "가-나-다"
    assert slug_part(" a\tb ") == "a-b"
    assert slug_part("") == ""


def test_slug_part_nfc_normalizes_decomposed() -> None:
    # NFC 정규화로 분해형(NFD) 한글이 결합형과 같은 slug 가 된다 — doc_id 안정성 보장.
    # NFC 를 제거하면 NFD 입력이 분해된 코드포인트로 남아 결합형과 달라져 KILL.
    nfd = unicodedata.normalize("NFD", "가 나")
    assert len(nfd) != len("가 나")  # 분해형은 코드포인트 수가 다름(전제 확인)
    assert slug_part(nfd) == slug_part("가 나") == "가-나"


# ---- normalize_file_format ----

def test_normalize_file_format_prefers_value_then_suffix() -> None:
    # value 가 있으면 lower + 선행 "." 제거 후 우선(파일명 suffix 보다 앞섬).
    assert normalize_file_format(".PDF", "x.hwp") == "pdf"
    # value 가 비면 파일명 suffix 로 fallback.
    assert normalize_file_format("", "doc.HWP") == "hwp"
    assert normalize_file_format(None, "a.pdf") == "pdf"
    # 둘 다 비면 빈 문자열.
    assert normalize_file_format("", "noext") == ""
