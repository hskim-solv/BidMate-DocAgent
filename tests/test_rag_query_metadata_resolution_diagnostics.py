"""Unit coverage for rag_query.metadata_resolution_diagnostics decision/reason (issue #2382).

``metadata_resolution_diagnostics``(rag_query.py:431)는 메타데이터 해소 진단
dict 를 빌드하며 핵심으로 clarify/use_selected_candidates decision 을 결정하는
import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위 테스트가
0건이었다. test-only, 소스 무수정.

핵심 변별:
- decision: ambiguous=False → use_selected_candidates; True+non-comparison → clarify;
  True+comparison → use_selected_candidates(예외 분기).
- decision 인자 명시 시 그대로 우선.
- decision_reason: reason 인자 → metadata_ambiguity.reason → "".
- relaxed stage 의 selected_candidates_by_stage 는 항상 [].
"""
from __future__ import annotations

from typing import Any

from rag_query import metadata_resolution_diagnostics


def _decision(analysis: dict[str, Any]) -> str:
    return metadata_resolution_diagnostics("쿼리", analysis)["ambiguity"]["decision"]


def test_decision_use_selected_when_not_ambiguous() -> None:
    # ambiguous=False → use_selected_candidates(clarify 아님).
    assert _decision({}) == "use_selected_candidates"
    assert _decision({"metadata_ambiguous": False, "query_type": "single_doc"}) == "use_selected_candidates"


def test_decision_clarify_when_ambiguous_and_not_comparison() -> None:
    # ambiguous=True + 비교 아님 → clarify.
    assert _decision({"metadata_ambiguous": True, "query_type": "single_doc"}) == "clarify"


def test_decision_use_selected_when_ambiguous_but_comparison() -> None:
    # ambiguous=True 라도 query_type=="comparison" 이면 clarify 하지 않는다(예외 분기 pin).
    assert _decision({"metadata_ambiguous": True, "query_type": "comparison"}) == "use_selected_candidates"


def test_explicit_decision_arg_overrides_computed() -> None:
    # decision 인자가 주어지면 ambiguous 계산을 무시하고 그대로 쓴다.
    out = metadata_resolution_diagnostics(
        "쿼리", {"metadata_ambiguous": True, "query_type": "single_doc"}, decision="forced"
    )
    assert out["ambiguity"]["decision"] == "forced"


def test_decision_reason_prefers_arg_then_ambiguity_then_empty() -> None:
    f = metadata_resolution_diagnostics
    # reason 인자 우선.
    assert f("q", {"metadata_ambiguity": {"reason": "amb_r"}}, reason="arg_r")["ambiguity"]["decision_reason"] == "arg_r"
    # reason 인자 없으면 metadata_ambiguity.reason 로 폴백.
    assert f("q", {"metadata_ambiguity": {"reason": "amb_r"}})["ambiguity"]["decision_reason"] == "amb_r"
    # 둘 다 없으면 "".
    assert f("q", {})["ambiguity"]["decision_reason"] == ""


def test_relaxed_stage_candidates_always_empty() -> None:
    # relaxed stage 의 후보는 빌드하지 않고 항상 빈 리스트로 고정.
    out = metadata_resolution_diagnostics("쿼리", {})
    assert out["selected_candidates_by_stage"]["relaxed"] == []
