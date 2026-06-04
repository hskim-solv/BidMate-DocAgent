"""Unit coverage for rag_query.py inspection predicates + state helpers (issue #2194).

``rag_query.py`` (596 LOC, 15 공개함수) 중 기존 테스트는 ``analyze_query`` 만
커버한다. 이 파일은 순수 query-inspection predicate + conversation-state 헬퍼
8종의 동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정). analyze_query/
make_plan/resolve_conversation_context 같은 retrieval 핵심 오케스트레이션은 별도
concern → follow-up.

- ``is_metadata_ambiguous`` / ``has_implicit_reference`` / ``has_comparison_request``
- ``extract_requested_agencies`` — ENTITY_RE 기반 명시 기관 추출(영숫자 upper, dedupe)
- ``active_state_terms`` / ``active_state_size`` — conversation-state 요약
- ``inject_entities_into_query`` — 누락 entity prepend(중복 skip)
- ``query_type_default_top_k`` — single_doc=4 / follow_up=6 / comparison=6 기본값

leaf 모듈(rag_conversation_state/rag_pipeline_presets/rag_metadata_processing/
rag_text_processing + stdlib, rag_core back-edge 0 = ADR 0045 보존). negative
assertion 으로 dedup/중복 skip/fallback 분기가 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_query import (
    active_state_size,
    active_state_terms,
    extract_requested_agencies,
    has_comparison_request,
    has_implicit_reference,
    inject_entities_into_query,
    is_metadata_ambiguous,
    query_type_default_top_k,
)


def _match(doc_id: str, confidence: float) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "field": "agency",
        "value": "v",
        "confidence": confidence,
        "agency": "A",
        "project": "",
    }


# --- has_implicit_reference ---


def test_has_implicit_reference_detects_pattern() -> None:
    assert has_implicit_reference("그 기관 예산은?") is True


def test_has_implicit_reference_false_for_explicit_query() -> None:
    assert has_implicit_reference("행정안전부 예산 알려줘") is False


# --- has_comparison_request ---


def test_has_comparison_request_detects_cue_words() -> None:
    assert has_comparison_request("A와 B 비교") is True
    assert has_comparison_request("각각 알려줘") is True


def test_has_comparison_request_false_without_cue() -> None:
    assert has_comparison_request("예산 얼마인가요?") is False


# --- is_metadata_ambiguous ---


def test_is_metadata_ambiguous_true_for_close_scores() -> None:
    # 0.95 vs 0.94 → AMBIGUOUS_CONFIDENCE_DELTA 내 → 모호
    assert is_metadata_ambiguous([_match("d1", 0.95), _match("d2", 0.94)], "single_doc") is True


def test_is_metadata_ambiguous_false_for_single_and_comparison() -> None:
    assert is_metadata_ambiguous([_match("d1", 0.95)], "single_doc") is False
    # comparison 은 다중 타깃 허용이라 항상 비모호
    assert is_metadata_ambiguous([_match("d1", 0.95), _match("d2", 0.94)], "comparison") is False
    assert is_metadata_ambiguous([], "single_doc") is False


# --- extract_requested_agencies ---


def test_extract_requested_agencies_dedupes() -> None:
    out = extract_requested_agencies("기관 A와 기관 B 그리고 기관 A")
    assert out == ["기관 A", "기관 B"]
    assert len(out) == 2  # 중복 '기관 A' 한 번만


def test_extract_requested_agencies_uppercases_alphanumeric() -> None:
    assert extract_requested_agencies("기관 abc 예산") == ["기관 ABC"]


def test_extract_requested_agencies_empty_without_pattern() -> None:
    assert extract_requested_agencies("예산 얼마인가요?") == []


# --- active_state_terms ---


def test_active_state_terms_combines_agencies_and_projects() -> None:
    out = active_state_terms({"active_agencies": ["행안부"], "active_projects": ["사업A"]})
    assert out == ["행안부", "사업A"]


def test_active_state_terms_falls_back_to_doc_ids() -> None:
    # agencies/projects 가 비면 doc_ids 로 fallback
    out = active_state_terms({"active_doc_ids": ["d1", "d2"]})
    assert out == ["d1", "d2"]


def test_active_state_terms_empty_state() -> None:
    assert active_state_terms({}) == []


# --- active_state_size ---


def test_active_state_size_is_max_of_axes() -> None:
    size = active_state_size(
        {"active_agencies": ["a", "b"], "active_projects": ["x"], "active_doc_ids": []}
    )
    assert size == 2  # max(2, 1, 0)


# --- inject_entities_into_query ---


def test_inject_entities_prepends_missing() -> None:
    assert inject_entities_into_query("예산은?", ["행안부"]) == "행안부 예산은?"


def test_inject_entities_skips_already_present() -> None:
    # 이미 query 에 있는 entity 는 중복 추가하지 않는다
    assert inject_entities_into_query("행안부 예산", ["행안부"]) == "행안부 예산"


def test_inject_entities_empty_list_unchanged() -> None:
    assert inject_entities_into_query("예산", []) == "예산"


# --- query_type_default_top_k ---


def test_query_type_default_top_k_known_types() -> None:
    assert query_type_default_top_k("single_doc") == 4
    assert query_type_default_top_k("follow_up") == 6
    assert query_type_default_top_k("comparison") == 6


def test_query_type_default_top_k_unknown_falls_back_to_single_doc() -> None:
    # 미등록 query_type 은 single_doc 기본값(4)으로 fallback
    assert query_type_default_top_k("unknown_type") == 4
