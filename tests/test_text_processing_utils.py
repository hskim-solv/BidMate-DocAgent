"""Unit coverage for rag_text_processing.py normalization/token/split utils (issue #2164).

``rag_text_processing.py`` 의 10개 순수 텍스트 유틸 중 ``sentence_split`` 만
``tests/test_korean_sentence_split_regression.py`` 로 커버됨. 이 파일은 나머지
9개 함수의 동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정):

- ``normalize_entity`` / ``compact_metadata_text`` / ``normalize_metadata_token``
  (한국어 조사 suffix 반복 제거)
- ``ordered_unique`` / ``coerce_string_list`` / ``coerce_alias_values`` (구분자 split)
- ``tokenize`` (lower + stopword 필터) / ``split_long_text_unit`` (3분기 재귀)
- ``normalize_section_path`` (str/list/fallback)

leaf 모듈(korean_lexicon + stdlib 만 의존, rag_core back-edge 0 = ADR 0045 보존).
negative assertion 으로 정규화/필터가 실제로 일어나는지(non-vacuous) 못 박는다.
``sentence_split`` 회귀 테스트는 건드리지 않는다 (one-concern).
"""
from __future__ import annotations

from rag_text_processing import (
    coerce_alias_values,
    coerce_string_list,
    compact_metadata_text,
    normalize_entity,
    normalize_metadata_token,
    normalize_section_path,
    ordered_unique,
    split_long_text_unit,
    tokenize,
)


# --- normalize_entity ---


def test_normalize_entity_collapses_and_strips_whitespace() -> None:
    assert normalize_entity("  행안부   사업  ") == "행안부 사업"


def test_normalize_entity_already_clean_unchanged() -> None:
    assert normalize_entity("행안부") == "행안부"


# --- compact_metadata_text ---


def test_compact_metadata_text_drops_separators_and_lowercases() -> None:
    out = compact_metadata_text("행안-부 ABC (2024)")
    assert out == "행안부abc2024"
    # 정규화가 실제로 일어났는지: 구분자/대문자/괄호가 사라졌다
    assert "-" not in out
    assert " " not in out
    assert "(" not in out
    assert "ABC" not in out


# --- normalize_metadata_token ---


def test_normalize_metadata_token_strips_korean_particle() -> None:
    # '행안부는' → 조사 '는' 제거, '서울의' → '의' 제거
    assert normalize_metadata_token("행안부는") == "행안부"
    out = normalize_metadata_token("서울의")
    assert out == "서울"
    assert not out.endswith("의")  # 조사가 실제로 떨어졌다


def test_normalize_metadata_token_keeps_short_token() -> None:
    # len(token) > len(suffix) + 1 가드 → 1음절 조사 자체는 보존
    assert normalize_metadata_token("은") == "은"


def test_normalize_metadata_token_lowercases_alphanumeric() -> None:
    # 한글이 아니면 조사 루프를 타지 않고 NFC+lower 만 적용
    assert normalize_metadata_token("ABC123") == "abc123"


# --- ordered_unique ---


def test_ordered_unique_dedups_preserving_order() -> None:
    assert ordered_unique(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_ordered_unique_skips_falsy_values() -> None:
    out = ordered_unique(["", "x", "", "x"])
    assert out == ["x"]
    assert "" not in out  # 빈 문자열은 절대 통과하지 않는다


# --- coerce_string_list ---


def test_coerce_string_list_non_list_returns_empty() -> None:
    assert coerce_string_list("abc") == []
    assert coerce_string_list(None) == []


def test_coerce_string_list_strips_dedups_and_stringifies() -> None:
    # 공백 strip + dedup + 비문자열 str() 강제, 빈 항목 제거
    assert coerce_string_list([" a ", "a", "", 1]) == ["a", "1"]


# --- coerce_alias_values ---


def test_coerce_alias_values_splits_string_on_delimiters() -> None:
    # ,;/| 모두 구분자
    assert coerce_alias_values("a, b; c/d|e") == ["a", "b", "c", "d", "e"]


def test_coerce_alias_values_none_and_scalar_return_empty() -> None:
    assert coerce_alias_values(None) == []
    assert coerce_alias_values(42) == []


def test_coerce_alias_values_list_strips_and_dedups() -> None:
    assert coerce_alias_values([" x ", "x"]) == ["x"]


# --- tokenize ---


def test_tokenize_lowercases_strips_particles_and_filters_stopwords() -> None:
    out = tokenize("행안부 그리고 사업을 한다")
    # '사업을' → 조사 제거 → '사업', 'ABC' lower, '그리고' 는 stopword 라 제거
    assert "사업" in out
    assert "행안부" in out
    assert "그리고" not in out  # stopword 가 실제로 걸러졌다


def test_tokenize_lowercases_ascii() -> None:
    assert tokenize("ABC") == ["abc"]


# --- split_long_text_unit ---


def test_split_long_text_unit_short_returns_intact() -> None:
    assert split_long_text_unit("짧은글", 100) == ["짧은글"]


def test_split_long_text_unit_groups_multiline_lines() -> None:
    out = split_long_text_unit("첫째 줄입니다\n둘째 줄입니다\n셋째 줄", 18)
    assert out == ["첫째 줄입니다 둘째 줄입니다", "셋째 줄"]


def test_split_long_text_unit_single_line_splits_on_words() -> None:
    out = split_long_text_unit("가나다 라마바 사아자 차카타", 10)
    assert out == ["가나다 라마바", "사아자 차카타"]
    # 각 청크가 한도 이내
    assert all(len(chunk) <= 10 for chunk in out)


def test_split_long_text_unit_single_long_word_slices_by_chars() -> None:
    # 공백 없는 긴 단어는 max_chars 단위로 슬라이스
    assert split_long_text_unit("가나다라마바사아자차", 4) == ["가나다라", "마바사아", "자차"]


def test_split_long_text_unit_recurses_into_overlong_line() -> None:
    # 멀티라인 중 한 줄이 한도를 넘으면 그 줄만 재귀적으로 슬라이스
    out = split_long_text_unit("짧다\n" + "가" * 12, 5)
    assert out == ["짧다", "가가가가가", "가가가가가", "가가"]


# --- normalize_section_path ---


def test_normalize_section_path_splits_string_on_chevron() -> None:
    assert normalize_section_path({"section_path": "1장 > 2절 > 3항"}, "H") == [
        "1장",
        "2절",
        "3항",
    ]


def test_normalize_section_path_filters_blank_list_entries() -> None:
    out = normalize_section_path({"path": [" A ", "B", ""]}, "H")
    assert out == ["A", "B"]
    assert "" not in out  # 빈 항목 제거 확인


def test_normalize_section_path_falls_back_to_heading() -> None:
    # 빈 path 또는 str/list 가 아닌 값 → heading 단독
    assert normalize_section_path({}, "제목") == ["제목"]
    assert normalize_section_path({"section_path": 123}, "HD") == ["HD"]


def test_normalize_section_path_prefers_section_path_over_path() -> None:
    assert normalize_section_path({"section_path": "X", "path": "Y"}, "H") == ["X"]
