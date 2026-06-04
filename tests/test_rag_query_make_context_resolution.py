"""Unit coverage for rag_query.make_context_resolution (issue #2367).

``make_context_resolution`` 은 멀티턴 대화 컨텍스트 해소 결과를 8-key 고정
스키마 dict 로 빌드하는 import-safe leaf(rag_core/torch/chromadb 미로드,
ADR 0045)인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``confidence`` 는 ``round(float(_), 3)`` — 3자리 반올림.
- ``context_entities``/``context_projects``/``active_doc_ids`` 는 None → [] (or []).
- ``resolved_query`` 는 None 보존(빈 문자열로 강제하지 않음).
- 8-key 고정 스키마 + 제공 값 passthrough.
"""
from __future__ import annotations

from rag_query import make_context_resolution


def test_rounds_confidence_to_three_decimals() -> None:
    # confidence 는 round(float(_), 3). 0.123456 → 0.123:
    # round 제거 시 0.123456 노출, 자릿수 변경(2→0.12 / 4→0.1235)도 모두 KILL.
    assert make_context_resolution("resolved", "history", 0.123456)["confidence"] == 0.123


def test_defaults_none_lists_to_empty_and_preserves_none_query() -> None:
    out = make_context_resolution("ambiguous", "none", 0.0)
    # None 리스트 인자 → [] ("or []" 폴백 제거 시 None 으로 KILL).
    assert out["context_entities"] == []
    assert out["context_projects"] == []
    assert out["active_doc_ids"] == []
    # resolved_query 는 None 보존 — 다른 키와 달리 "or" 폴백이 없으므로
    # "" 등으로 강제하는 mutation 을 잡는다.
    assert out["resolved_query"] is None
    # reason 기본값은 "".
    assert out["reason"] == ""


def test_passes_through_all_provided_values() -> None:
    # 8-key 고정 스키마 전체 — 키 누락/오타/값 뒤바뀜이면 dict 동등성에서 KILL.
    out = make_context_resolution(
        "resolved", "entity", 0.9, reason="matched",
        resolved_query="서울시 예산",
        context_entities=["기관 A"], context_projects=["P1"], active_doc_ids=["d1"],
    )
    assert out == {
        "status": "resolved",
        "source": "entity",
        "confidence": 0.9,
        "reason": "matched",
        "resolved_query": "서울시 예산",
        "context_entities": ["기관 A"],
        "context_projects": ["P1"],
        "active_doc_ids": ["d1"],
    }


def test_confidence_coerced_to_float_type() -> None:
    # confidence 는 round(float(_), 3) — float() 제거 시 int 입력에 int 가 그대로
    # 남는다. 값 동등성(1 == 1.0)으론 구분 불가하므로 타입을 고정해 float() 캐스트를 pin.
    assert type(make_context_resolution("resolved", "history", 1)["confidence"]) is float
