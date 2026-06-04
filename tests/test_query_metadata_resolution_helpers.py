"""Unit coverage for rag_query.py metadata-resolution 구성 헬퍼 (issue #2210).

``rag_query.py`` 의 순수 metadata-resolution 구성 헬퍼 4종을 oracle 로 고정한다
(#2194 predicates follow-up, test-only, 소스 무수정). retrieval 핵심 오케스트레이션
(analyze_query/resolve_conversation_context/make_plan)은 별도 concern → follow-up.

- ``make_context_resolution`` — context-resolution dict 빌더. confidence round(3),
  resolved_query 기본 None, ``or []`` 3종
- ``comparison_targets_for_analysis`` — (targets, field) 3분기. matched_doc_ids≥2
  → doc_id(우선) / entities≥2 → agency / else ([], "")
- ``summarize_metadata_match`` — match→9키 요약, .get 기본값
- ``metadata_resolution_diagnostics`` — 진단 dict. selected_by_stage(strict≥0.90/
  reduced≥0.70/relaxed 항상 빈), decision 분기(ambiguous AND query_type≠comparison
  → clarify, 명시 override), ambiguity 병합

leaf 모듈(rag_text_processing/rag_metadata_processing/rag_conversation_state +
stdlib, rag_core back-edge 0 = ADR 0045). negative assertion 으로 round·우선순위·
분기 가드·dedup 이 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_query import (
    comparison_targets_for_analysis,
    make_context_resolution,
    metadata_resolution_diagnostics,
    summarize_metadata_match,
)


# --- make_context_resolution ---


def test_make_context_resolution_rounds_confidence_to_3dp() -> None:
    out = make_context_resolution("resolved", "conversation_state", 0.87654)
    assert out["confidence"] == 0.877  # round(3)
    assert out["status"] == "resolved"
    assert out["source"] == "conversation_state"


def test_make_context_resolution_defaults() -> None:
    out = make_context_resolution("s", "x", 0.5)
    # resolved_query 기본 None — 빈 리스트가 아니라 None
    assert out["resolved_query"] is None
    # or [] 3종: None → 빈 리스트
    assert out["context_entities"] == []
    assert out["context_projects"] == []
    assert out["active_doc_ids"] == []
    assert out["reason"] == ""


def test_make_context_resolution_preserves_explicit_values() -> None:
    out = make_context_resolution(
        "s", "x", 0.5, reason="r", resolved_query="q2", context_entities=["e"]
    )
    assert out["resolved_query"] == "q2"
    assert out["context_entities"] == ["e"]
    assert out["reason"] == "r"


# --- comparison_targets_for_analysis ---


def test_comparison_targets_prefers_doc_ids_when_two_or_more() -> None:
    # doc_id 가 entities 보다 우선 — entities 가 있어도 doc_ids≥2 면 doc_id
    targets, field = comparison_targets_for_analysis(
        {"matched_doc_ids": ["d1", "d2", "d1"], "entities": ["e1", "e2"]}
    )
    assert targets == ["d1", "d2"]  # ordered_unique dedup
    assert field == "doc_id"


def test_comparison_targets_falls_back_to_agencies() -> None:
    targets, field = comparison_targets_for_analysis(
        {"matched_doc_ids": ["d1"], "entities": ["행안부", "교육부", "행안부"]}
    )
    assert targets == ["행안부", "교육부"]  # ordered_unique dedup
    assert field == "agency"


def test_comparison_targets_empty_when_insufficient() -> None:
    assert comparison_targets_for_analysis({"matched_doc_ids": ["d1"], "entities": ["e1"]}) == ([], "")
    assert comparison_targets_for_analysis({}) == ([], "")


# --- summarize_metadata_match ---


def test_summarize_metadata_match_projects_nine_keys() -> None:
    out = summarize_metadata_match(
        {"doc_id": "d1", "field": "agency", "confidence": 0.9, "matched_terms": ["t"]}
    )
    assert set(out.keys()) == {
        "doc_id", "field", "value", "agency", "project",
        "confidence", "stage", "match_type", "matched_terms",
    }
    assert out["confidence"] == 0.9
    assert out["matched_terms"] == ["t"]


def test_summarize_metadata_match_defaults_for_missing() -> None:
    out = summarize_metadata_match({})
    # 문자열 키는 "", confidence 는 0.0, matched_terms 는 []
    assert out["value"] == ""
    assert out["stage"] == ""
    assert out["confidence"] == 0.0
    assert out["matched_terms"] == []


# --- metadata_resolution_diagnostics ---


def _match(doc_id: str, confidence: float) -> dict[str, Any]:
    return {"doc_id": doc_id, "confidence": confidence}


def test_diagnostics_counts_and_relaxed_always_empty() -> None:
    analysis = {"metadata_matches": [_match("d1", 0.95), _match("d2", 0.75)]}
    out = metadata_resolution_diagnostics("행안부 예산", analysis)
    assert out["candidate_count"] == 2
    # relaxed stage 는 언제나 빈 리스트(현 구현 placeholder)
    assert out["selected_candidates_by_stage"]["relaxed"] == []


def test_diagnostics_stage_thresholds() -> None:
    # strict≥0.90, reduced≥0.70 — 0.75 는 reduced 에만, 0.95 는 양쪽
    analysis = {"metadata_matches": [_match("d1", 0.95), _match("d2", 0.75)]}
    out = metadata_resolution_diagnostics("q", analysis)
    strict = [c["doc_id"] for c in out["selected_candidates_by_stage"]["strict"]]
    reduced = [c["doc_id"] for c in out["selected_candidates_by_stage"]["reduced"]]
    assert strict == ["d1"]
    assert reduced == ["d1", "d2"]


def test_diagnostics_selected_doc_ids_follow_selected_stage() -> None:
    analysis = {"metadata_matches": [_match("d1", 0.95), _match("d2", 0.75)]}
    out = metadata_resolution_diagnostics("q", analysis, selected_stage="strict")
    assert out["selected_doc_ids"] == ["d1"]


def test_diagnostics_selected_doc_ids_deduped() -> None:
    # 같은 stage 에 doc_id 가 중복된 매치가 들어와도 selected_doc_ids 는
    # ordered_unique 로 dedup 된다(2 후보 → 1 doc_id). dedup 래퍼 제거 mutant KILL.
    analysis = {"metadata_matches": [_match("dX", 0.75), _match("dX", 0.72)]}
    out = metadata_resolution_diagnostics("q", analysis, selected_stage="reduced")
    assert len(out["selected_candidates_by_stage"]["reduced"]) == 2
    assert out["selected_doc_ids"] == ["dX"]


def test_diagnostics_decision_clarify_when_ambiguous_non_comparison() -> None:
    analysis = {
        "metadata_matches": [_match("d1", 0.95)],
        "metadata_ambiguous": True,
        "query_type": "single_doc",
    }
    out = metadata_resolution_diagnostics("q", analysis)
    assert out["ambiguity"]["decision"] == "clarify"
    assert out["ambiguity"]["ambiguous"] is True


def test_diagnostics_decision_not_clarify_for_comparison() -> None:
    # query_type 가드: ambiguous 라도 comparison 이면 clarify 하지 않는다
    analysis = {
        "metadata_matches": [_match("d1", 0.95)],
        "metadata_ambiguous": True,
        "query_type": "comparison",
    }
    out = metadata_resolution_diagnostics("q", analysis)
    assert out["ambiguity"]["decision"] == "use_selected_candidates"


def test_diagnostics_decision_use_selected_when_not_ambiguous() -> None:
    analysis = {"metadata_matches": [_match("d1", 0.95)], "metadata_ambiguous": False}
    out = metadata_resolution_diagnostics("q", analysis)
    assert out["ambiguity"]["decision"] == "use_selected_candidates"


def test_diagnostics_explicit_decision_overrides() -> None:
    analysis = {"metadata_matches": [_match("d1", 0.95)], "metadata_ambiguous": True}
    out = metadata_resolution_diagnostics("q", analysis, decision="custom")
    assert out["ambiguity"]["decision"] == "custom"


def test_diagnostics_merges_ambiguity_and_overrides_reason() -> None:
    analysis = {
        "metadata_matches": [_match("d1", 0.95)],
        "metadata_ambiguity": {"reason": "orig", "extra": "kept"},
    }
    out = metadata_resolution_diagnostics("q", analysis, reason="new")
    # 기존 ambiguity 필드는 병합 보존, reason 인자는 decision_reason 을 덮어씀
    assert out["ambiguity"]["extra"] == "kept"
    assert out["ambiguity"]["decision_reason"] == "new"


def test_diagnostics_decision_reason_falls_back_to_ambiguity_reason() -> None:
    # reason 인자가 빈 문자열(기본)이면 `reason or ambiguity.get("reason")` 폴백 →
    # 원래 ambiguity.reason 으로 채워진다. 폴백 분기 제거 mutant KILL.
    analysis = {
        "metadata_matches": [_match("d1", 0.95)],
        "metadata_ambiguity": {"reason": "orig"},
    }
    out = metadata_resolution_diagnostics("q", analysis)  # reason="" 기본
    assert out["ambiguity"]["decision_reason"] == "orig"
