"""Unit coverage for rag_indexing chunking-option decision helpers.

``validate_chunking_options`` 와 ``resolve_chunking_strategy`` 는 청킹
파이프라인 진입점을 가드하는 순수·결정적 헬퍼다 (``build_chunk_records`` 가
입력·전략 검증과 문서별 전략 선택에 각각 의존). 직접 단위 테스트가 없어
다음을 oracle 로 고정한다:

- ``validate_chunking_options``: 4종 전략 수용, max_chars/overlap 경계,
  ValueError 메시지(정렬된 선택지 목록 포함), 그리고 다중 invalid 시
  strategy → max_chars → overlap 단락(short-circuit) 순서.
- ``resolve_chunking_strategy``: ``contextual`` → ``auto`` coercion 후 구조
  기반 section/fixed 분기, 명시적 전략의 무검증 passthrough(빈 doc 에도 구조
  검사를 하지 않음), 입력 doc 비변형.

모든 기대값은 소스 실행으로 캡처했다. 음성 단언(negative assertion) 위주로,
경계·순서·passthrough 가 회귀하면 실패하도록 구성한다.
"""

from __future__ import annotations

import copy

import pytest

from rag_indexing import resolve_chunking_strategy, validate_chunking_options


def _structured_doc() -> dict:
    """2개 이상의 텍스트 섹션 → ``document_has_section_structure`` 가 True."""
    return {
        "doc_id": "d-struct",
        "title": "구조 문서",
        "sections": [
            {"heading": "개요", "text": "사업 개요 본문"},
            {"heading": "사업 범위", "text": "범위 본문"},
        ],
    }


def _flat_doc() -> dict:
    """단일 약한 heading('본문') → 구조 없음 → fixed 로 해석."""
    return {
        "doc_id": "d-flat",
        "title": "평문 문서",
        "sections": [{"heading": "본문", "text": "단일 본문 텍스트"}],
    }


# ----------------------------------------------------------------------
# validate_chunking_options
# ----------------------------------------------------------------------

VALID_STRATEGIES = ("auto", "section", "fixed", "contextual")


@pytest.mark.parametrize("strategy", VALID_STRATEGIES)
def test_validate_accepts_every_known_strategy(strategy: str) -> None:
    # contextual 은 resolve 가 auto 로 coerce 하지만, validate 단계에선 합법값.
    # 4종 모두 None 을 반환해야 한다(예외 없음).
    assert validate_chunking_options(strategy, 500, 1) is None


def test_validate_accepts_boundary_max_chars_one_and_zero_overlap() -> None:
    # 경계값: max_chars==1(>=1), overlap==0(>=0) 은 유효.
    # ``< 1`` / ``< 0`` 가 ``<= 1`` / ``<= 0`` 로 약화되면 이 단언이 깨진다.
    assert validate_chunking_options("section", 1, 0) is None


def test_validate_rejects_unknown_strategy_with_sorted_choice_message() -> None:
    # 선택지 목록은 정렬되어 노출된다(auto, contextual, fixed, section).
    with pytest.raises(
        ValueError,
        match=r"chunking_strategy must be one of: auto, contextual, fixed, section",
    ):
        validate_chunking_options("bogus", 500, 1)


@pytest.mark.parametrize("bad_max", [0, -5])
def test_validate_rejects_nonpositive_max_chars(bad_max: int) -> None:
    with pytest.raises(ValueError, match=r"chunk_max_chars must be positive\."):
        validate_chunking_options("section", bad_max, 1)


def test_validate_rejects_negative_overlap() -> None:
    with pytest.raises(
        ValueError, match=r"chunk_overlap_sentences must be zero or positive\."
    ):
        validate_chunking_options("section", 500, -1)


def test_validate_short_circuits_strategy_before_numeric_checks() -> None:
    # 세 인자 모두 invalid 여도 strategy 가 먼저 검사되어 strategy 메시지만 보고된다.
    with pytest.raises(ValueError, match=r"chunking_strategy must be one of"):
        validate_chunking_options("bogus", 0, -1)


def test_validate_checks_max_chars_before_overlap() -> None:
    # 유효 strategy + bad max + bad overlap: overlap 이 아니라 max_chars 가 먼저 보고된다.
    with pytest.raises(ValueError, match=r"chunk_max_chars must be positive\."):
        validate_chunking_options("section", 0, -1)


# ----------------------------------------------------------------------
# resolve_chunking_strategy
# ----------------------------------------------------------------------


def test_resolve_contextual_coerces_through_auto_to_section_on_structured_doc() -> None:
    # contextual → auto → 구조 있음 → "section". contextual 을 그대로 반환하지 않음.
    assert resolve_chunking_strategy(_structured_doc(), "contextual") == "section"


def test_resolve_contextual_coerces_through_auto_to_fixed_on_flat_doc() -> None:
    assert resolve_chunking_strategy(_flat_doc(), "contextual") == "fixed"


def test_resolve_auto_selects_section_for_structured_doc() -> None:
    assert resolve_chunking_strategy(_structured_doc(), "auto") == "section"


def test_resolve_auto_selects_fixed_for_flat_doc() -> None:
    assert resolve_chunking_strategy(_flat_doc(), "auto") == "fixed"


def test_resolve_explicit_section_passes_through_without_structure_check() -> None:
    # 명시적 "section" 은 구조 검사를 건너뛴다 — 구조 정보 없는 {} 에도 그대로 반환.
    # 명시 경로가 구조 기반 재해석으로 바뀌면 {} 는 "fixed" 로 해석되어 "section"
    # 기대와 어긋난다(KeyError 가 아니라 반환값 발산으로 포착됨).
    assert resolve_chunking_strategy({}, "section") == "section"


def test_resolve_explicit_fixed_passes_through_without_structure_check() -> None:
    # {} 는 구조 기반 해석으로도 "fixed" 라 단독으론 재해석 회귀와 구별 못 한다.
    # 구조가 있으면 "section" 이 될 structured doc 으로 passthrough(무재해석)를 독립 고정한다.
    assert resolve_chunking_strategy({}, "fixed") == "fixed"
    assert resolve_chunking_strategy(_structured_doc(), "fixed") == "fixed"


def test_resolve_does_not_validate_unknown_explicit_strategy() -> None:
    # resolve 는 전략을 검증하지 않는다(검증은 validate_chunking_options 책임).
    # 미지값도 그대로 passthrough 되어야 한다.
    assert resolve_chunking_strategy(_flat_doc(), "weird") == "weird"


def test_resolve_does_not_mutate_input_doc() -> None:
    # contextual 분기는 지역 변수만 재할당한다 — 입력 doc 은 불변이어야 한다.
    doc = _flat_doc()
    before = copy.deepcopy(doc)
    resolve_chunking_strategy(doc, "contextual")
    assert doc == before
