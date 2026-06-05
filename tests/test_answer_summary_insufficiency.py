"""Unit coverage for rag_answer.py 요약·보류 빌더 (issue #2244).

``rag_answer.py`` 의 답변 요약·보류(abstention) 빌더 3종을 oracle 로 고정한다
(ADR 0003/0004, test-only, 소스 무수정). 직접 단위 import 기존 0.

- ``answer_verification_reasons`` — comparison 일 때 missing_requested_entities 를
  'missing_requested_entity:{e}' reason 으로 추가(dedup). non-comparison 은 그대로
- ``answer_summary`` — status별 4분기(INSUFFICIENT 보류 문구 / PARTIAL 일부 근거+
  missing suffix / comparison compact_claims / supported claim join)
- ``build_insufficiency`` — missing_targets(checked_entities - supported),
  not verified+no missing→checked 전체 fallback, reasons fallback('verification_failed')

leaf 모듈(rag_verifier 등 + stdlib, rag_core back-edge 0 = ADR 0045). abstention
일급 상태 계약 표면. negative assertion 으로 comparison 가드·dedup·status 분기·
fallback 이 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_answer import (
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_SUPPORTED,
    answer_summary,
    answer_verification_reasons,
    build_insufficiency,
)


# --- answer_verification_reasons ---


def test_verification_reasons_non_comparison_unchanged() -> None:
    # comparison 이 아니면 verification_reasons 를 그대로 통과
    assert answer_verification_reasons({"query_type": "single_doc"}, ["r1"]) == ["r1"]


def test_verification_reasons_non_comparison_ignores_missing_entities() -> None:
    # non-comparison 은 missing_requested_entities 키가 present+populated 여도 append
    # 하지 않는다. producer(rag_query)가 이 키를 모든 query_type 에 emit 하므로
    # query_type 가드가 load-bearing — 가드를 always-true 로 약화하면 spurious
    # 'missing_requested_entity:' reason 이 새어 KILL.
    out = answer_verification_reasons(
        {"query_type": "single_doc", "missing_requested_entities": ["행안부"]}, ["r1"]
    )
    assert out == ["r1"]


def test_verification_reasons_comparison_appends_missing() -> None:
    out = answer_verification_reasons(
        {"query_type": "comparison", "missing_requested_entities": ["행안부"]}, ["r1"]
    )
    assert out == ["r1", "missing_requested_entity:행안부"]


def test_verification_reasons_comparison_dedupes() -> None:
    # 이미 같은 reason 이 있으면 중복 추가하지 않는다
    out = answer_verification_reasons(
        {"query_type": "comparison", "missing_requested_entities": ["행안부"]},
        ["missing_requested_entity:행안부"],
    )
    assert out == ["missing_requested_entity:행안부"]


# --- answer_summary ---


def _claims() -> list[dict[str, Any]]:
    return [{"target": "행안부", "claim": "예산 1조"}]


def test_answer_summary_insufficient_is_abstention_message() -> None:
    out = answer_summary("질의", {}, [], ANSWER_STATUS_INSUFFICIENT, None)
    assert out == "제공된 공개 샘플 RFP 근거에서는 '질의'에 답할 수 있는 내용을 찾지 못했습니다."


def test_answer_summary_partial_appends_missing_suffix() -> None:
    out = answer_summary("q", {}, _claims(), ANSWER_STATUS_PARTIAL, {"missing_targets": ["교육부"]})
    assert out == "일부 근거만 확인했습니다. 행안부: 예산 1조 확인되지 않은 대상: 교육부."


def test_answer_summary_partial_without_missing_has_no_suffix() -> None:
    out = answer_summary("q", {}, _claims(), ANSWER_STATUS_PARTIAL, None)
    assert out == "일부 근거만 확인했습니다. 행안부: 예산 1조"
    assert "확인되지 않은 대상" not in out


def test_answer_summary_comparison_uses_compact_claims() -> None:
    out = answer_summary("q", {"query_type": "comparison"}, _claims(), ANSWER_STATUS_SUPPORTED, None)
    assert out == "행안부: 예산 1조"  # target: claim 형식


def test_answer_summary_supported_joins_claim_text_only() -> None:
    # 일반 supported(비교 아님)은 target 없이 claim 텍스트만 join
    out = answer_summary("q", {"query_type": "single_doc"}, _claims(), ANSWER_STATUS_SUPPORTED, None)
    assert out == "예산 1조"


# --- build_insufficiency ---


def test_build_insufficiency_missing_targets_is_unsupported_entities() -> None:
    out = build_insufficiency(
        "q", {"entities": ["행안부", "교육부"]}, [{"target": "행안부"}], True, ["reason1"]
    )
    assert out["missing_targets"] == ["교육부"]  # 지원된 행안부 제외
    assert out["reasons"] == ["reason1"]
    assert out["checked_entities"] == ["행안부", "교육부"]


def test_build_insufficiency_uses_context_entities_and_matched_doc_ids() -> None:
    out = build_insufficiency(
        "q",
        {"context_entities": ["이전기관"], "matched_doc_ids": ["doc-1", "doc-2"]},
        [],
        True,
        [],
    )
    assert out["missing_targets"] == ["이전기관"]
    assert out["checked_entities"] == ["이전기관"]
    assert out["checked_doc_ids"] == ["doc-1", "doc-2"]


def test_build_insufficiency_not_verified_no_missing_falls_back_to_all_checked() -> None:
    # not verified 인데 missing_targets 가 비고 checked_entities 가 있으면 전체를 missing 으로
    out = build_insufficiency("q", {"entities": ["행안부"]}, [{"target": "행안부"}], False, [])
    assert out["missing_targets"] == ["행안부"]
    # reasons 가 비고 not verified → 'verification_failed' fallback
    assert out["reasons"] == ["verification_failed"]


def test_build_insufficiency_verified_empty_reasons_stays_empty() -> None:
    # verified 이고 reasons 가 비면 fallback 없이 빈 리스트
    out = build_insufficiency("q", {"entities": ["행안부"]}, [{"target": "행안부"}], True, [])
    assert out["reasons"] == []
