"""Unit coverage for rag_conversation_state.py (issue #2150).

Leaf module (imports only stdlib; rag_core imports the public symbols
back) with ZERO prior direct test coverage. These lock the
conversation-state schema shape and the defensive normalization
contract that ``run_rag_query`` relies on across multi-turn requests:
every field that fails its type contract must fall back to the
empty-schema default rather than propagate malformed external state.

rag_core integration (multi-turn run_rag_query e2e) is out of scope.
"""
from __future__ import annotations

from rag_conversation_state import (
    AMBIGUOUS_CONFIDENCE_DELTA,
    CONTEXT_RESOLUTION_THRESHOLD,
    CONVERSATION_STATE_SCHEMA_VERSION,
    MAX_CONVERSATION_TURNS,
    _coerce_string_list,
    _ordered_unique,
    empty_conversation_state,
    normalize_conversation_state,
)


# --- _ordered_unique ---


def test_ordered_unique_empty() -> None:
    assert _ordered_unique([]) == []


def test_ordered_unique_dedupes_preserving_order() -> None:
    assert _ordered_unique(["c", "a", "c", "b", "a"]) == ["c", "a", "b"]


def test_ordered_unique_drops_falsy() -> None:
    """빈 문자열 등 falsy 항목은 제거된다."""
    assert _ordered_unique(["a", "", "b", ""]) == ["a", "b"]


# --- _coerce_string_list ---


def test_coerce_string_list_non_list_returns_empty() -> None:
    """list 가 아닌 입력(None/str/int/dict)은 모두 빈 리스트."""
    for bad in (None, "abc", 123, {"k": "v"}):
        assert _coerce_string_list(bad) == []


def test_coerce_string_list_trims_dedupes_drops_empty() -> None:
    assert _coerce_string_list([" a ", "a", "  ", "b"]) == ["a", "b"]


def test_coerce_string_list_coerces_non_string_items() -> None:
    """항목은 ``str()`` 로 강제된 뒤 trim/dedup 된다."""
    assert _coerce_string_list([1, 2, 2]) == ["1", "2"]


# --- empty_conversation_state ---


def test_empty_state_schema_shape() -> None:
    assert empty_conversation_state() == {
        "schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
        "active_agencies": [],
        "active_projects": [],
        "active_topics": [],
        "active_doc_ids": [],
        "active_candidates": [],
        "confidence": 0.0,
        "ambiguous": False,
        "turns": [],
    }


def test_empty_state_returns_independent_instances() -> None:
    """매 호출 새 dict + 중첩 리스트도 공유되지 않는다(factory 계약)."""
    a = empty_conversation_state()
    b = empty_conversation_state()
    assert a is not b
    a["turns"].append({"x": 1})
    assert b["turns"] == []


# --- normalize: 비정상 입력 → empty ---


def test_normalize_none_or_non_dict_returns_empty() -> None:
    empty = empty_conversation_state()
    for bad in (None, [], "x", 5):
        assert normalize_conversation_state(bad) == empty  # type: ignore[arg-type]


def test_normalize_empty_dict_returns_empty() -> None:
    assert normalize_conversation_state({}) == empty_conversation_state()


# --- normalize: schema_version (or 기본값 분기) ---


def test_normalize_schema_version_falsy_defaults_else_passthrough() -> None:
    """0/falsy → 기본 버전(``or`` 분기), 명시 값은 int 로 보존."""
    assert (
        normalize_conversation_state({"schema_version": 0})["schema_version"]
        == CONVERSATION_STATE_SCHEMA_VERSION
    )
    assert normalize_conversation_state({"schema_version": 5})["schema_version"] == 5


# --- normalize: string-list 필드 정제 ---


def test_normalize_string_list_fields_coerced() -> None:
    out = normalize_conversation_state(
        {
            "active_agencies": [" 행안부 ", "행안부", ""],
            "active_topics": "not-a-list",  # non-list → []
        }
    )
    assert out["active_agencies"] == ["행안부"]
    assert out["active_topics"] == []


# --- normalize: active_candidates (마지막 8 + dict 필터) ---


def test_normalize_active_candidates_keeps_last_8_dicts() -> None:
    cands = [{"i": n} for n in range(10)]
    out = normalize_conversation_state({"active_candidates": cands})
    assert out["active_candidates"] == [{"i": n} for n in range(2, 10)]


def test_normalize_active_candidates_filters_non_dict() -> None:
    out = normalize_conversation_state(
        {"active_candidates": [{"a": 1}, "x", 3, {"b": 2}]}
    )
    assert out["active_candidates"] == [{"a": 1}, {"b": 2}]


def test_normalize_active_candidates_non_list_empty() -> None:
    assert (
        normalize_conversation_state({"active_candidates": "x"})["active_candidates"]
        == []
    )


# --- normalize: confidence (round 3 + ValueError fallback) ---


def test_normalize_confidence_rounds_to_three() -> None:
    assert normalize_conversation_state({"confidence": 0.123456})["confidence"] == 0.123


def test_normalize_confidence_string_parsed() -> None:
    assert normalize_conversation_state({"confidence": "0.7"})["confidence"] == 0.7


def test_normalize_confidence_invalid_or_none_falls_to_zero() -> None:
    assert normalize_conversation_state({"confidence": "bad"})["confidence"] == 0.0
    assert normalize_conversation_state({"confidence": None})["confidence"] == 0.0


# --- normalize: ambiguous (bool 강제) ---


def test_normalize_ambiguous_coerced_to_bool() -> None:
    assert normalize_conversation_state({"ambiguous": 1})["ambiguous"] is True
    assert normalize_conversation_state({"ambiguous": 0})["ambiguous"] is False
    assert normalize_conversation_state({})["ambiguous"] is False


# --- normalize: turns (마지막 MAX + dict 필터) ---


def test_normalize_turns_capped_at_max_and_dict_only() -> None:
    turns = [{"t": n} for n in range(MAX_CONVERSATION_TURNS + 5)]
    out = normalize_conversation_state({"turns": turns})
    assert len(out["turns"]) == MAX_CONVERSATION_TURNS
    assert out["turns"][0] == {"t": 5}  # 마지막 12 (range(17)[-12:] 시작)


def test_normalize_turns_filters_non_dict() -> None:
    out = normalize_conversation_state(
        {"turns": [{"a": 1}, "x", None, {"b": 2}]}
    )
    assert out["turns"] == [{"a": 1}, {"b": 2}]


def test_normalize_turns_non_list_empty() -> None:
    assert normalize_conversation_state({"turns": "x"})["turns"] == []


# --- 모듈 상수 sanity (cap/threshold 회귀 가드) ---


def test_module_constants() -> None:
    assert CONVERSATION_STATE_SCHEMA_VERSION == 1
    assert MAX_CONVERSATION_TURNS == 12
    assert CONTEXT_RESOLUTION_THRESHOLD == 0.70
    assert AMBIGUOUS_CONFIDENCE_DELTA == 0.05
