"""Unit coverage for rag_metadata_processing.py normalization helpers (issue #2168).

``rag_metadata_processing.py`` (479 LOC)는 직접 단위 테스트 0이었다. 이 파일은
1차로 순수 정규화 헬퍼 5종의 동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정):

- ``metadata_tokens`` — TOKEN_RE + 조사 정규화 + stopword 필터
- ``normalize_regions`` — citation region 정규화(non-dict 스킵, bbox len 가드,
  page_number None 보존, source/type/block_id str 강제)
- ``normalize_page_span`` — [start,end] 직접 또는 regions min/max fallback
- ``normalize_document_sections`` — 섹션 정규화(section_id 포맷, 빈 text 스킵)
- ``document_has_section_structure`` — 섹션 구조 유무 bool(WEAK_SECTION_HEADINGS)

leaf 3종(rag_text_processing/rag_conversation_state/korean_lexicon + stdlib 만
의존, rag_core back-edge 0 = ADR 0045 보존). matching 파이프라인(match/dedupe/ambiguity)은
별도 concern 이라 follow-up. negative assertion 으로 정규화/필터가 실제로 일어나는지
(non-vacuous) 못 박는다.
"""
from __future__ import annotations

from rag_metadata_processing import (
    document_has_section_structure,
    metadata_tokens,
    normalize_document_sections,
    normalize_page_span,
    normalize_regions,
)


# --- metadata_tokens ---


def test_metadata_tokens_strips_particles_and_stopwords() -> None:
    out = metadata_tokens("행안부 사업을 한다")
    assert out == ["행안부", "사업", "한다"]
    # '사업을' 의 조사 '을' 이 실제로 떨어졌다 (붙은 원형이 남지 않음)
    assert "사업을" not in out


def test_metadata_tokens_empty_string() -> None:
    assert metadata_tokens("") == []


# --- normalize_regions ---


def test_normalize_regions_keeps_geometry_and_stringifies_ids() -> None:
    out = normalize_regions(
        [{"page_number": 3, "bbox": [1, 2, 3, 4], "source": "pdf", "block_id": 7}]
    )
    # block_id 정수가 str 로 강제됨, page_number/bbox 는 그대로
    assert out == [
        {"page_number": 3, "bbox": [1, 2, 3, 4], "source": "pdf", "block_id": "7"}
    ]


def test_normalize_regions_non_list_returns_empty() -> None:
    assert normalize_regions("nope") == []
    assert normalize_regions(None) == []


def test_normalize_regions_skips_non_dict_items() -> None:
    out = normalize_regions(["x", {"page_number": 1}, 42])
    # 문자열/정수 항목은 버려지고 dict 만 통과
    assert out == [{"page_number": 1, "bbox": None}]
    assert len(out) == 1


def test_normalize_regions_drops_malformed_bbox() -> None:
    # bbox 길이가 4가 아니면 bbox 키 자체가 빠진다 (page_number 키 부재 → None)
    out = normalize_regions([{"bbox": [1, 2, 3]}])
    assert out == [{"page_number": None}]
    assert "bbox" not in out[0]


def test_normalize_regions_preserves_explicit_none_page() -> None:
    out = normalize_regions([{"page_number": None, "type": "fig"}])
    assert out == [{"page_number": None, "bbox": None, "type": "fig"}]


def test_normalize_regions_rejects_boolean_page_number() -> None:
    out = normalize_regions([{"page_number": True}])
    assert out == [{"bbox": None}]
    assert "page_number" not in out[0]


def test_normalize_regions_rejects_false_page_number() -> None:
    out = normalize_regions([{"page_number": False}])
    assert out == [{"bbox": None}]
    assert "page_number" not in out[0]


def test_normalize_regions_rejects_float_page_number() -> None:
    out = normalize_regions([{"page_number": 1.9}])
    assert out == [{"bbox": None}]
    assert "page_number" not in out[0]


def test_normalize_regions_coerces_numeric_string_page_number() -> None:
    out = normalize_regions([{"page_number": "3"}])
    assert out == [{"page_number": 3, "bbox": None}]


def test_normalize_regions_coerces_whitespace_numeric_string_page_number() -> None:
    out = normalize_regions([{"page_number": " \t3\n"}])
    assert out == [{"page_number": 3, "bbox": None}]


def test_normalize_regions_rejects_decimal_string_page_number() -> None:
    out = normalize_regions([{"page_number": "3.0"}])
    assert out == [{"bbox": None}]
    assert "page_number" not in out[0]


def test_normalize_regions_rejects_whitespace_decimal_string_page_number() -> None:
    out = normalize_regions([{"page_number": " \t3.0\n"}])
    assert out == [{"bbox": None}]
    assert "page_number" not in out[0]


def test_normalize_regions_rejects_nonpositive_page_numbers() -> None:
    out = normalize_regions([{"page_number": 0}, {"page_number": -2}])
    assert out == [{"bbox": None}, {"bbox": None}]
    assert all("page_number" not in region for region in out)


# --- normalize_page_span ---


def test_normalize_page_span_uses_explicit_pair() -> None:
    assert normalize_page_span([5, 9], []) == [5, 9]


def test_normalize_page_span_coerces_explicit_string_pair() -> None:
    assert normalize_page_span(["5", "9"], []) == [5, 9]


def test_normalize_page_span_coerces_whitespace_string_pair() -> None:
    assert normalize_page_span([" 5 ", "\t9\n"], []) == [5, 9]


def test_normalize_page_span_rejects_decimal_string_explicit_pair() -> None:
    assert normalize_page_span(["3.0", "4"], []) is None


def test_normalize_page_span_sorts_explicit_pair() -> None:
    assert normalize_page_span([9, 5], []) == [5, 9]


def test_normalize_page_span_rejects_boolean_explicit_pair() -> None:
    assert normalize_page_span([True, 3], []) is None


def test_normalize_page_span_rejects_false_explicit_pair() -> None:
    assert normalize_page_span([False, 3], []) is None


def test_normalize_page_span_rejects_nonpositive_explicit_pair() -> None:
    assert normalize_page_span([0, 3], []) is None
    assert normalize_page_span([-1, 3], []) is None


def test_normalize_page_span_rejects_float_explicit_pair() -> None:
    assert normalize_page_span([1.9, 3.1], []) is None


def test_normalize_page_span_falls_back_to_region_min_max() -> None:
    regions = [{"page_number": 7}, {"page_number": 3}, {"page_number": 5}]
    assert normalize_page_span(None, regions) == [3, 7]


def test_normalize_page_span_returns_none_without_pages() -> None:
    out = normalize_page_span(None, [{"bbox": [1, 2, 3, 4]}])
    assert out is None  # 페이지 정보 없으면 span 없음


def test_normalize_page_span_ignores_wrong_length_pair() -> None:
    # len != 2 인 value 는 직접 경로를 타지 않고 regions fallback
    assert normalize_page_span([1, 2, 3], [{"page_number": 4}]) == [4, 4]


def test_normalize_page_span_wrong_length_pair_without_region_pages_is_none() -> None:
    assert normalize_page_span([1, 2, 3], []) is None


def test_normalize_page_span_invalid_string_pair_falls_back_to_regions() -> None:
    assert normalize_page_span(["bad", "span"], [{"page_number": 4}]) == [4, 4]


def test_normalize_page_span_invalid_pair_without_region_pages_is_none() -> None:
    assert normalize_page_span(["bad", "span"], [{"bbox": [1, 2, 3, 4]}]) is None


def test_normalize_page_span_ignores_boolean_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": True}, {"page_number": 3}]) == [
        3,
        3,
    ]


def test_normalize_page_span_uses_numeric_string_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": "3"}, {"page_number": 5}]) == [
        3,
        5,
    ]


def test_normalize_page_span_coerces_whitespace_string_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": " 3 "}, {"page_number": "\t5\n"}]) == [
        3,
        5,
    ]


def test_normalize_page_span_ignores_decimal_string_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": "3.0"}, {"page_number": 5}]) == [
        5,
        5,
    ]


def test_normalize_page_span_ignores_nonpositive_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": 0}, {"page_number": -1}, {"page_number": 3}]) == [
        3,
        3,
    ]


def test_normalize_page_span_ignores_float_region_pages() -> None:
    assert normalize_page_span(None, [{"page_number": 1.9}, {"page_number": 3}]) == [
        3,
        3,
    ]


# --- normalize_document_sections ---


def test_normalize_document_sections_formats_id_and_skips_empty_text() -> None:
    doc = {
        "doc_id": "D1",
        "title": "제목",
        "agency": "행안부",
        "sections": [
            {"heading": "1장", "text": "본문입니다"},
            {"heading": "", "text": ""},  # 빈 text → 스킵
        ],
    }
    out = normalize_document_sections(doc)
    assert len(out) == 1  # 빈 text 섹션 제외
    section = out[0]
    assert section["section_id"] == "D1::section-001"
    assert section["section"] == "1장"
    assert section["doc_id"] == "D1"
    assert section["agency"] == "행안부"


def test_normalize_document_sections_empty_when_no_sections() -> None:
    assert normalize_document_sections({"doc_id": "D", "title": "T", "sections": []}) == []


# --- document_has_section_structure ---


def test_document_has_section_structure_true_for_multiple_sections() -> None:
    doc = {
        "doc_id": "D",
        "title": "T",
        "sections": [
            {"heading": "A", "text": "x"},
            {"heading": "B", "text": "y"},
        ],
    }
    assert document_has_section_structure(doc) is True


def test_document_has_section_structure_false_for_weak_single_heading() -> None:
    # 단일 섹션 + WEAK_SECTION_HEADINGS('본문') → 구조 없음
    doc = {"doc_id": "D", "title": "T", "sections": [{"heading": "본문", "text": "x"}]}
    assert document_has_section_structure(doc) is False


def test_document_has_section_structure_false_when_empty() -> None:
    assert (
        document_has_section_structure({"doc_id": "D", "title": "T", "sections": []})
        is False
    )


def test_document_has_section_structure_true_for_strong_single_heading() -> None:
    # 단일 섹션이라도 heading 이 WEAK 목록에 없으면 구조 있음
    doc = {"doc_id": "D", "title": "T", "sections": [{"heading": "제3조 계약", "text": "x"}]}
    assert document_has_section_structure(doc) is True
