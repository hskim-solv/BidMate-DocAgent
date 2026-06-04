"""Unit coverage for rag_answer answer_query_type/answer_summary 파생 (issue #2390).

``answer_query_type``(rag_answer.py:392)와 ``answer_summary``(rag_answer.py:402)는
검증 status + analysis 로부터 사용자 노출 답변의 type 라벨과 요약 문자열을 파생하는
작은 순수 import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위
테스트가 0건이었다. test-only, 소스 무수정.

핵심 변별:
- answer_query_type — status==insufficient 면 query_type 무관 "abstention"(precedence);
  그 외 comparison/follow_up/그 외·키부재 매핑.
- answer_summary — insufficient 고정 메시지(claims 무시), partial prefix+missing suffix,
  sufficient comparison(``target: claim`` compact) vs 비-comparison(claim 텍스트만) 출력 구분.
"""
from __future__ import annotations

from typing import Any

from rag_answer import (
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    answer_query_type,
    answer_summary,
)

_CLAIMS: list[dict[str, Any]] = [
    {"target": "기관A", "claim": "예산 10억"},
    {"target": "기관B", "claim": "기간 12개월"},
]


# ---- answer_query_type ----

def test_answer_query_type_status_insufficient_precedes_query_type() -> None:
    # status==insufficient 면 query_type 이 comparison 이라도 "abstention"(status 우선).
    assert answer_query_type({"query_type": "comparison"}, ANSWER_STATUS_INSUFFICIENT) == "abstention"
    # partial 은 insufficient 가 아니므로 query_type 분기로 빠진다(abstention 아님).
    assert answer_query_type({"query_type": "comparison"}, ANSWER_STATUS_PARTIAL) == "comparison"


def test_answer_query_type_maps_each_query_type() -> None:
    # insufficient 아닌 status 하에서 query_type 별 매핑.
    assert answer_query_type({"query_type": "comparison"}, "sufficient") == "comparison"
    assert answer_query_type({"query_type": "follow_up"}, "sufficient") == "follow_up"
    assert answer_query_type({"query_type": "single_doc"}, "sufficient") == "single_doc"
    # 미지 query_type / 키 부재 → "single_doc" 기본.
    assert answer_query_type({"query_type": "weird"}, "sufficient") == "single_doc"
    assert answer_query_type({}, "sufficient") == "single_doc"


# ---- answer_summary ----

def test_answer_summary_insufficient_fixed_message_ignores_claims() -> None:
    # insufficient → query 보간 고정 메시지, claims 는 무시.
    out = answer_summary("이 사업 예산은?", {}, _CLAIMS, ANSWER_STATUS_INSUFFICIENT, None)
    assert out == "제공된 공개 샘플 RFP 근거에서는 '이 사업 예산은?'에 답할 수 있는 내용을 찾지 못했습니다."
    # claim 텍스트가 새어나오지 않음(고정 메시지 contract).
    assert "예산 10억" not in out


def test_answer_summary_partial_prefix_and_missing_suffix() -> None:
    # partial → 안내 prefix + compact(target: claim) + missing suffix.
    out = answer_summary("q", {}, _CLAIMS, ANSWER_STATUS_PARTIAL, {"missing_targets": ["기관C", "기관D"]})
    assert out == "일부 근거만 확인했습니다. 기관A: 예산 10억 기관B: 기간 12개월 확인되지 않은 대상: 기관C, 기관D."


def test_answer_summary_partial_no_suffix_when_missing_empty_or_none() -> None:
    base = "일부 근거만 확인했습니다. 기관A: 예산 10억 기관B: 기간 12개월"
    # insufficiency=None → suffix 없음(`(insufficiency or {})` 가드).
    assert answer_summary("q", {}, _CLAIMS, ANSWER_STATUS_PARTIAL, None) == base
    # missing_targets 빈 리스트 → suffix 없음(`if missing` 게이트).
    assert answer_summary("q", {}, _CLAIMS, ANSWER_STATUS_PARTIAL, {"missing_targets": []}) == base
    # suffix 누락 시 "확인되지 않은 대상" 문구가 안 붙음.
    assert "확인되지 않은 대상" not in base


def test_answer_summary_comparison_includes_target_noncomparison_claim_only() -> None:
    # sufficient + comparison → "target: claim" compact(타깃 prefix 포함).
    comp = answer_summary("q", {"query_type": "comparison"}, _CLAIMS, "sufficient", None)
    assert comp == "기관A: 예산 10억 기관B: 기간 12개월"
    # sufficient + 비-comparison → claim 텍스트만(타깃 prefix 없음) — comparison 분기와 구분.
    noncomp = answer_summary("q", {"query_type": "single_doc"}, _CLAIMS, "sufficient", None)
    assert noncomp == "예산 10억 기간 12개월"
    # 두 출력은 달라야 한다(분기 교체 mutant 차단).
    assert comp != noncomp
    assert "기관A:" not in noncomp
