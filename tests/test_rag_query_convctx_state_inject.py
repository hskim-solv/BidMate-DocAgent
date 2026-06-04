"""Unit coverage for rag_query 대화 컨텍스트 상태/엔티티 주입 helper (issue #2344).

``active_state_terms`` / ``active_state_size`` / ``inject_entities_into_query`` 은
멀티턴 대화 컨텍스트를 추적·증강하는 import-safe leaf(rag_core/torch/chromadb
미로드, ADR 0045)인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``active_state_size`` — agencies/projects/doc_ids 중 최대 길이(None→0 가드).
- ``active_state_terms`` — agencies+projects ordered_unique, 없으면 doc_ids fallback.
- ``inject_entities_into_query`` — missing 엔티티만 prepend(case-insensitive 중복
  skip, falsy 제외, 없으면 원본).
"""
from __future__ import annotations

from typing import Any

from rag_query import (
    active_state_size,
    active_state_terms,
    inject_entities_into_query,
)


# ---- active_state_size ----

def test_active_state_size_is_max_across_axes() -> None:
    # 세 축(agencies/projects/doc_ids) 중 최대 길이(합산이면 KILL).
    state = {"active_agencies": ["a"], "active_projects": ["p1", "p2", "p3"], "active_doc_ids": ["d"]}
    assert active_state_size(state) == 3
    # 단일 축.
    assert active_state_size({"active_agencies": ["a", "b"]}) == 2


def test_active_state_size_zero_on_empty_or_none() -> None:
    # 빈 dict → 0, None 값도 `or []` 가드로 0(len(None) 크래시면 KILL).
    assert active_state_size({}) == 0
    assert active_state_size({"active_agencies": None}) == 0


def test_active_state_size_counts_doc_ids_axis() -> None:
    # doc_ids 가 단독 최대 축일 때도 반영 — max 에서 doc_ids 항을 빼면
    # agencies(1) 만 남아 1 을 반환해 KILL(다른 두 테스트는 projects 가 최대 축).
    assert active_state_size({"active_agencies": ["a"], "active_doc_ids": ["d1", "d2", "d3"]}) == 3


# ---- active_state_terms ----

def test_active_state_terms_unions_agencies_and_projects_unique() -> None:
    # agencies + projects 를 합쳐 순서 유지 중복 제거('b' 중복 → 1회).
    state = {"active_agencies": ["a", "b"], "active_projects": ["b", "c"]}
    assert active_state_terms(state) == ["a", "b", "c"]


def test_active_state_terms_falls_back_to_doc_ids() -> None:
    # agencies/projects 가 모두 비면 doc_ids fallback.
    assert active_state_terms({"active_doc_ids": ["d1", "d2"]}) == ["d1", "d2"]
    # 빈 상태 → [].
    assert active_state_terms({}) == []


def test_active_state_terms_ignores_doc_ids_when_agencies_present() -> None:
    # agencies/projects 가 하나라도 있으면 doc_ids 는 무시(fallback 무조건이면 KILL).
    assert active_state_terms({"active_agencies": ["a"], "active_doc_ids": ["d"]}) == ["a"]


# ---- inject_entities_into_query ----

def test_inject_prepends_only_missing_entities() -> None:
    # 쿼리에 없는 엔티티만 앞에 prepend, 순서 보존.
    assert inject_entities_into_query("예산은?", ["기관 A", "기관 B"]) == "기관 A 기관 B 예산은?"


def test_inject_skips_case_insensitive_duplicates() -> None:
    # 이미 쿼리에 (대소문자 무시) 있는 엔티티는 skip → 무변경.
    assert inject_entities_into_query("기관 a 예산", ["기관 A"]) == "기관 a 예산"


def test_inject_noop_on_empty_or_all_present() -> None:
    # 엔티티 없음 → 원본 그대로.
    assert inject_entities_into_query("원래 쿼리", []) == "원래 쿼리"
    # 전부 이미 present → 원본 그대로.
    assert inject_entities_into_query("기관 A 예산", ["기관 A"]) == "기관 A 예산"


def test_inject_filters_falsy_entities() -> None:
    # falsy(빈 문자열·None) 엔티티는 제외 — `entity and` guard 가 .lower() 호출
    # 전에 차단한다. None 은 list[str] 계약 밖이지만 guard 의 방어 동작을 pin
    # (guard 제거 시 None.lower() AttributeError 로 KILL; 빈 문자열만으론
    # `not in` 체크가 subsume 해 guard 가 미검증으로 남는다).
    entities: list[Any] = ["", None, "기관 X"]
    assert inject_entities_into_query("q", entities) == "기관 X q"
