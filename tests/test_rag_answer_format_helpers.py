"""Unit coverage for rag_answer 포매팅/타겟 helper (issue #2386).

``claim_target``/``citation_label``/``format_metadata_claim_value`` 은 ADR 0003
답변 계약의 citation/claim 표면 표현을 형성하는 작은 순수 import-safe leaf
(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위 테스트가 0건이었다.
test-only, 소스 무수정.

핵심 변별:
- claim_target — agency→title→doc_id→"unknown" 우선순위(빈 값 skip).
- citation_label — page_span 없으면 None; basis 별 prefix; 단일 p.N / 범위 pp.N-M.
- format_metadata_claim_value — budget int/float 콤마 포매팅, 그 외 str.
"""
from __future__ import annotations

from rag_answer import citation_label, claim_target, format_metadata_claim_value


# ---- claim_target ----

def test_claim_target_priority_agency_first() -> None:
    # agency > title > doc_id > "unknown" 우선순위.
    assert claim_target({"agency": "기관A", "title": "T", "doc_id": "D"}) == "기관A"
    assert claim_target({"title": "T", "doc_id": "D"}) == "T"
    assert claim_target({"doc_id": "D"}) == "D"
    # 비문자 메타값도 str() 로 정규화(계약상 dict[str, Any] → doc_id int 허용).
    assert claim_target({"doc_id": 123}) == "123"


def test_claim_target_skips_falsy_and_defaults_unknown() -> None:
    # 빈 문자열은 falsy 라 다음 우선순위로 skip; 전부 없으면 "unknown".
    assert claim_target({"agency": "", "title": "T"}) == "T"
    assert claim_target({}) == "unknown"


# ---- citation_label ----

def test_citation_label_none_when_no_page_span() -> None:
    # page_span 이 None/빈 → None(라벨 없음).
    assert citation_label("source_pdf", None) is None
    assert citation_label("source_pdf", []) is None


def test_citation_label_basis_prefix() -> None:
    # citation_basis 별 prefix 선택.
    assert citation_label("source_pdf", [3, 3]) == "원본 PDF p.3"
    assert citation_label("libreoffice_converted_pdf", [1, 1]) == "LibreOffice 변환 PDF p.1"
    # 미지 basis → 기본 "PDF".
    assert citation_label("unknown_basis", [2, 2]) == "PDF p.2"


def test_citation_label_single_vs_range_page() -> None:
    # 시작==끝 → p.N; 다르면 pp.N-M.
    assert citation_label("source_pdf", [3, 3]) == "원본 PDF p.3"
    assert citation_label("source_pdf", [3, 5]) == "원본 PDF pp.3-5"


# ---- format_metadata_claim_value ----

def test_format_budget_integer_and_float() -> None:
    # budget + int → 콤마 + "원".
    assert format_metadata_claim_value("budget", 1000000) == "1,000,000원"
    # 정수값 float → int 로 콤마(소수점 없음).
    assert format_metadata_claim_value("budget", 1000.0) == "1,000원"
    # 비정수 float → ,.2f.
    assert format_metadata_claim_value("budget", 1000000.5) == "1,000,000.50원"


def test_format_non_budget_or_non_numeric_is_str() -> None:
    # budget 아닌 key → str(value)(포매팅 없음).
    assert format_metadata_claim_value("name", "서울시") == "서울시"
    # budget 이라도 숫자 아니면 포매팅 안 함(isinstance 가드).
    assert format_metadata_claim_value("budget", "1억") == "1억"
