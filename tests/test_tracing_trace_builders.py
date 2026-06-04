"""Unit coverage for rag_tracing.py trace 빌더 3종 (issue #2206).

``rag_tracing.py`` trace 구성 함수 중 기존 테스트는 ``build_result_trace`` /
``redact_trace`` 만 커버. 이 파일은 나머지 trace 빌더 3종의 dict 계약을 oracle 로
고정한다 (test-only, 소스 무수정). percentile/rate/strip_internal_scores 는 #2198
에서 커버됨.

- ``summarize_stage_attempt`` — plan→stage summary. ``.get`` 기본값, retrieve_ms/
  verify_ms round(2), comparison_coverage 조건부 추가, retrieval_mode 기본 'flat'
- ``build_query_rewrite_trace`` — rewrite_type 4분기(conversation_state_prefix 는
  rewritten AND source 둘 다 필요 / explicit_context / clarification_required /
  none), confidence round(3), readable_summary 분기
- ``build_planner_trace`` — attempts 컴프(verified bool/metadata_doc_ids),
  stage_latencies 3키 round(2), bool cast(metadata_first/rerank/verifier_retry)

leaf 모듈(rag_metadata_processing + stdlib, rag_core back-edge 0 = ADR 0045).
negative assertion 으로 round·조건부-키·분기 가드가 실제로 일어나는지 못 박는다
(round 생략·무조건-add·source-only 분기 mutant 를 KILL).
"""
from __future__ import annotations

from typing import Any

from rag_tracing import (
    build_planner_trace,
    build_query_rewrite_trace,
    summarize_stage_attempt,
)


# --- summarize_stage_attempt ---


def test_summarize_stage_attempt_rounds_timings_to_2dp() -> None:
    # round(12.345, 2) = 12.35 — round 생략 mutant 면 12.345 가 남아 KILL
    out = summarize_stage_attempt(
        {"filter_stage": "strict"}, True, ["ok"], timings={"retrieve_ms": 12.345, "verify_ms": 3.0}
    )
    assert out["retrieve_ms"] == 12.35
    assert out["verify_ms"] == 3.0
    assert out["verified"] is True
    assert out["verification_reasons"] == ["ok"]


def test_summarize_stage_attempt_defaults_for_missing_plan_keys() -> None:
    out = summarize_stage_attempt({}, False, [])
    # `or {}` 기본값 — None 이 아니라 빈 dict
    assert out["metadata_filters"] == {}
    assert out["retrieval_budget"] == {}
    # 명시 기본값
    assert out["filter_fallback_used"] is False
    assert out["retrieval_mode"] == "flat"
    # timings=None → 0.0
    assert out["retrieve_ms"] == 0.0
    assert out["verify_ms"] == 0.0


def test_summarize_stage_attempt_omits_comparison_coverage_when_none() -> None:
    # comparison_coverage 가 None(미설정)이면 키 자체를 넣지 않는다
    out = summarize_stage_attempt({"filter_stage": "strict"}, True, [])
    assert "comparison_coverage" not in out


def test_summarize_stage_attempt_includes_comparison_coverage_when_present() -> None:
    out = summarize_stage_attempt({"comparison_coverage": 0.5}, True, [])
    assert out["comparison_coverage"] == 0.5


def test_summarize_stage_attempt_preserves_explicit_retrieval_mode() -> None:
    out = summarize_stage_attempt({"retrieval_mode": "parent_section"}, True, [])
    assert out["retrieval_mode"] == "parent_section"


# --- build_query_rewrite_trace ---


def test_rewrite_trace_conversation_state_prefix() -> None:
    out = build_query_rewrite_trace(
        "q", "행안부 q", {"source": "conversation_state", "confidence": 0.876}
    )
    assert out["rewrite_type"] == "conversation_state_prefix"
    assert out["rewritten"] is True
    assert out["context_resolution_confidence"] == 0.876  # round(3)
    assert out["readable_summary"] == "conversation_state_prefix: q -> 행안부 q"


def test_rewrite_trace_conversation_state_requires_actual_rewrite() -> None:
    # source 가 conversation_state 라도 resolved==original 이면 rewritten=False →
    # conversation_state_prefix 가드(rewritten AND source) 미충족 → none 으로 폴백.
    # 가드를 source-only 로 약화한 mutant 면 conversation_state_prefix 가 나와 KILL.
    out = build_query_rewrite_trace("q", "q", {"source": "conversation_state", "confidence": 0.5})
    assert out["rewritten"] is False
    assert out["rewrite_type"] == "none"


def test_rewrite_trace_explicit_context() -> None:
    out = build_query_rewrite_trace("q", "q", {"source": "context_entities"})
    assert out["rewrite_type"] == "explicit_context"
    assert out["context_source"] == "context_entities"


def test_rewrite_trace_clarification_required() -> None:
    out = build_query_rewrite_trace("q", "", {"status": "needs_clarification"})
    assert out["rewrite_type"] == "clarification_required"
    # resolved 빈 문자열 → original 로 대체
    assert out["resolved_query"] == "q"


def test_rewrite_trace_none_defaults() -> None:
    out = build_query_rewrite_trace("q", "q", {})
    assert out["rewrite_type"] == "none"
    assert out["context_source"] == "none"  # source 기본 'none'
    assert out["context_resolution_confidence"] == 0.0
    assert out["context_entities"] == []
    assert out["readable_summary"] == "none: query used without text rewrite"


def test_rewrite_trace_rounds_confidence_to_3dp() -> None:
    out = build_query_rewrite_trace("q", "q2", {"source": "x", "confidence": 0.123456})
    assert out["context_resolution_confidence"] == 0.123


# --- build_planner_trace ---


def _planner_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    analysis = {"query_type": "comparison", "metadata_ambiguous": True}
    plan = {
        "pipeline": "agentic_full",
        "filter_stage": "strict",
        "top_k": 6,
        "metadata_first": 1,
        "rerank": 1,
        "verifier_retry": 0,
    }
    metadata_resolution = {"selected_doc_ids": ["d1", "d2"], "candidate_count": 5}
    return analysis, plan, metadata_resolution


def test_planner_trace_attempts_projection() -> None:
    analysis, plan, mres = _planner_inputs()
    # verified=2 (truthy non-1) — bool cast 면 True, raw passthrough mutant 면 2 가
    # 남는다. 2 == True 는 False 라 아래 dict equality 가 그 mutant 를 KILL
    # (1 == True 였다면 dict 비교가 통과해버려 cast 검증이 vacuous 했을 것).
    attempts = [{"stage": "strict", "top_k": 6, "verified": 2, "metadata_filters": {"doc_ids": ["d1"]}}]
    out = build_planner_trace(analysis, plan, mres, ["strict", "reduced"], attempts)
    a = out["attempts"][0]
    assert a == {
        "stage": "strict",
        "top_k": 6,
        "verified": True,  # bool cast(2→True)
        "verification_reasons": [],  # 누락 시 기본 []
        "metadata_doc_ids": ["d1"],  # metadata_filters.doc_ids 추출
    }
    assert a["verified"] is True  # identity — passthrough mutant 이중 방어


def test_planner_trace_bool_casts_plan_flags() -> None:
    analysis, plan, mres = _planner_inputs()
    out = build_planner_trace(analysis, plan, mres, [], [])
    # 1/0 정수 plan 플래그가 진짜 bool 로 정규화된다
    assert out["metadata_first"] is True
    assert out["rerank"] is True
    assert out["verifier_retry"] is False
    assert out["metadata_ambiguous"] is True


def test_planner_trace_rounds_latencies_to_2dp() -> None:
    analysis, plan, mres = _planner_inputs()
    out = build_planner_trace(
        analysis, plan, mres, [], [], stage_latencies_ms={"query_analysis_ms": 1.234}
    )
    assert out["stage_latencies_ms"] == {
        "query_analysis_ms": 1.23,  # round(2)
        "context_resolution_ms": 0.0,  # 누락 키도 0.0 으로 채움
        "answer_generation_ms": 0.0,
    }


def test_planner_trace_readable_summary() -> None:
    analysis, plan, mres = _planner_inputs()
    out = build_planner_trace(analysis, plan, mres, ["strict"], [])
    assert (
        out["readable_summary"]
        == "comparison planned with agentic_full stage=strict top_k=6 metadata_docs=['d1', 'd2']"
    )
