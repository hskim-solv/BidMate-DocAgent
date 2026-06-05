"""Unit coverage for rag_answer.py pure format helpers (issue #2155).

rag_answer.py 의 순수 포맷 helper 가 직접 테스트 0 (기존
``test_answer_contract_snapshot`` / ``test_answer_status_reason_enum`` 은
답변 dict 계약·enum 만 커버). 이 파일은 외부 의존이 없는 3개 포맷 함수의
RFP 도메인 계약을 고정한다:

- ``claim_target``: agency→title→doc_id→"unknown" fallback chain
- ``citation_label``: page_span 포맷 (None / basis prefix / single vs range)
- ``format_metadata_claim_value``: budget 한국 통화 포맷

``best_sentence`` / ``sentence_has_verification_topic`` 등
``verification_topics`` / ``sentence_split`` / ``tokenize`` 의존 helper 는
범위 외 (follow-up).
"""
from __future__ import annotations

from rag_answer import (
    citation_label,
    claim_target,
    format_metadata_claim_value,
    make_citation,
)


# --- claim_target: agency → title → doc_id → "unknown" fallback chain ---


def test_claim_target_prefers_agency() -> None:
    assert (
        claim_target({"agency": "행정안전부", "title": "T", "doc_id": "d"})
        == "행정안전부"
    )


def test_claim_target_falls_back_to_title_then_doc_id() -> None:
    assert claim_target({"title": "사업명", "doc_id": "d"}) == "사업명"
    assert claim_target({"doc_id": "rfp-001"}) == "rfp-001"


def test_claim_target_empty_item_is_unknown() -> None:
    assert claim_target({}) == "unknown"


def test_claim_target_skips_falsy_fields_in_chain() -> None:
    """빈 문자열/None 은 falsy → or chain 이 다음 후보로 넘어간다."""
    assert claim_target({"agency": "", "title": "T"}) == "T"
    assert claim_target({"agency": None, "title": None, "doc_id": "d"}) == "d"


def test_claim_target_coerces_to_str() -> None:
    assert claim_target({"agency": 123}) == "123"


# --- citation_label: page_span 포맷 ---


def test_citation_label_none_when_no_page_span() -> None:
    assert citation_label("source_pdf", None) is None
    assert citation_label("source_pdf", []) is None


def test_citation_label_basis_prefix() -> None:
    assert (
        citation_label("libreoffice_converted_pdf", [3, 3])
        == "LibreOffice 변환 PDF p.3"
    )
    assert citation_label("source_pdf", [3, 3]) == "원본 PDF p.3"
    # 알 수 없는 basis → 기본 "PDF"
    assert citation_label("something_else", [3, 3]) == "PDF p.3"


def test_citation_label_single_vs_range_page() -> None:
    assert citation_label("source_pdf", [7, 7]) == "원본 PDF p.7"  # single
    assert citation_label("source_pdf", [3, 5]) == "원본 PDF pp.3-5"  # range


# --- make_citation: canonical PDF metadata passthrough ---


def test_make_citation_preserves_canonical_pdf_metadata_and_label() -> None:
    citation = make_citation({
        "doc_id": "rfp-001",
        "chunk_id": "chunk-7",
        "title": "공고문",
        "section": "입찰 개요",
        "agency": "조달청",
        "section_path": ["root", 2],
        "page_span": [2, 4],
        "text_span_hash": "span-sha",
        "metadata": {
            "text_source": "pdf_pymupdf4llm",
            "citation_basis": "source_pdf",
            "converted_pdf_sha256": "converted-sha",
            "converted_pdf_page_count": 12,
            "citation_pdf_sha256": "citation-sha",
            "citation_pdf_page_count": 8,
        },
    })

    assert citation == {
        "doc_id": "rfp-001",
        "chunk_id": "chunk-7",
        "title": "공고문",
        "section": "입찰 개요",
        "agency": "조달청",
        "section_path": ["root", "2"],
        "page_span": [2, 4],
        "text_source": "pdf_pymupdf4llm",
        "citation_basis": "source_pdf",
        "converted_pdf_sha256": "converted-sha",
        "converted_pdf_page_count": 12,
        "citation_pdf_sha256": "citation-sha",
        "citation_pdf_page_count": 8,
        "text_span_hash": "span-sha",
        "citation_label": "원본 PDF pp.2-4",
    }


def test_make_citation_omits_empty_canonical_pdf_metadata() -> None:
    citation = make_citation({
        "doc_id": "rfp-001",
        "chunk_id": "chunk-7",
        "title": "공고문",
        "page_span": [1, 1],
        "metadata": {
            "text_source": "pdf_pymupdf4llm",
            "citation_basis": "",
            "converted_pdf_sha256": "",
            "converted_pdf_page_count": None,
            "citation_pdf_sha256": "citation-sha",
            "citation_pdf_page_count": "",
        },
    })

    assert citation["text_source"] == "pdf_pymupdf4llm"
    assert citation["citation_pdf_sha256"] == "citation-sha"
    assert citation["citation_label"] == "PDF p.1"
    assert "citation_basis" not in citation
    assert "converted_pdf_sha256" not in citation
    assert "converted_pdf_page_count" not in citation
    assert "citation_pdf_page_count" not in citation


def test_make_citation_treats_non_dict_metadata_as_empty() -> None:
    citation = make_citation({
        "doc_id": "rfp-001",
        "chunk_id": "chunk-7",
        "title": "공고문",
        "page_span": [4, 4],
        "metadata": ["not", "a", "dict"],
        "text_span_hash": "span-sha",
    })

    assert citation == {
        "doc_id": "rfp-001",
        "chunk_id": "chunk-7",
        "title": "공고문",
        "section": "",
        "agency": "",
        "page_span": [4, 4],
    }


# --- format_metadata_claim_value: budget 한국 통화 포맷 ---


def test_format_budget_int_thousands_separator() -> None:
    assert format_metadata_claim_value("budget", 1000000) == "1,000,000원"
    assert format_metadata_claim_value("budget", 0) == "0원"


def test_format_budget_integer_float_drops_decimals() -> None:
    """정수값 float(예: 1000.0)은 int 로 변환되어 소수점 없이 표시."""
    assert format_metadata_claim_value("budget", 1000.0) == "1,000원"


def test_format_budget_decimal_float_keeps_two_decimals() -> None:
    assert format_metadata_claim_value("budget", 1234.5) == "1,234.50원"
    assert format_metadata_claim_value("budget", 1234.56) == "1,234.56원"


def test_format_budget_non_numeric_passthrough() -> None:
    """budget 이라도 비-숫자값은 str() passthrough (예: '비공개')."""
    assert format_metadata_claim_value("budget", "비공개") == "비공개"


def test_format_non_budget_key_is_str() -> None:
    """budget 이 아닌 키는 통화 포맷 없이 str()."""
    assert format_metadata_claim_value("duration", 12) == "12"
    assert format_metadata_claim_value("agency", "행안부") == "행안부"
