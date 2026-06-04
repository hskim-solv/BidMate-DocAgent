"""Unit coverage for rag_answer.py 상태/타입 분류 헬퍼 (issue #2215).

``rag_answer.py`` 의 미커버 순수 분류 헬퍼 2종을 oracle 로 고정한다 (test-only,
소스 무수정). 포맷 헬퍼(claim_target/citation_label/format_metadata_claim_value)는
기존 ``tests/test_answer_format_helpers.py``(#2155)가 단위 커버 → 표면 중복 회피.

- ``answer_status`` — (analysis, claims, verified, reasons)→status. supported
  (verified+깨끗) / partial(verified+partial_topic+claims, 또는 comparison+claims
  +missing_comparison/requested) / insufficient. **claims 가드**(claims 없으면
  partial 불가)
- ``answer_query_type`` — status=insufficient→abstention(query_type 무관),
  comparison/follow_up/기타→single_doc

leaf 모듈(rag_verifier 등 + stdlib, rag_core back-edge 0 = ADR 0045). ADR 0003/
0004 답변 상태 계약 표면. negative assertion 으로 verified 가드·claims 가드·
status 우선·prefix 매칭 분기가 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from rag_answer import (
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_SUPPORTED,
    answer_query_type,
    answer_status,
)
from rag_verifier import PARTIAL_TOPIC_GROUNDING_REASON

_CLAIMS = [{"text": "c"}]  # non-empty claims


# --- answer_status: verified 경로 ---


def test_answer_status_supported_when_verified_and_clean() -> None:
    # verified + missing 없음 + partial_topic 없음 → supported
    assert answer_status({}, _CLAIMS, True, []) == ANSWER_STATUS_SUPPORTED


def test_answer_status_partial_for_verified_partial_topic() -> None:
    # verified 라도 relaxed-stage partial-topic grounding 이면 partial 로 약화
    out = answer_status({}, _CLAIMS, True, [PARTIAL_TOPIC_GROUNDING_REASON])
    assert out == ANSWER_STATUS_PARTIAL


def test_answer_status_insufficient_when_missing_requested_entity() -> None:
    # verified 여도 missing_requested_entity 가 있으면 supported 로 승격 안 됨.
    # comparison 도 아니므로 insufficient 로 떨어진다.
    out = answer_status({}, _CLAIMS, True, ["missing_requested_entity:행안부"])
    assert out == ANSWER_STATUS_INSUFFICIENT


# --- answer_status: comparison partial 경로 ---


def test_answer_status_partial_for_comparison_with_missing_comparison() -> None:
    out = answer_status(
        {"query_type": "comparison"}, _CLAIMS, False, ["missing_comparison:target"]
    )
    assert out == ANSWER_STATUS_PARTIAL


def test_answer_status_partial_for_comparison_with_missing_requested() -> None:
    out = answer_status(
        {"query_type": "comparison"}, _CLAIMS, False, ["missing_requested_entity:y"]
    )
    assert out == ANSWER_STATUS_PARTIAL


# --- answer_status: insufficient 경로 + claims 가드 ---


def test_answer_status_insufficient_when_not_verified_non_comparison() -> None:
    assert answer_status({}, _CLAIMS, False, ["some_reason"]) == ANSWER_STATUS_INSUFFICIENT


def test_answer_status_comparison_requires_claims() -> None:
    # claims 가드: comparison + missing_comparison 이어도 claims 가 비면 partial 불가
    out = answer_status({"query_type": "comparison"}, [], False, ["missing_comparison:x"])
    assert out == ANSWER_STATUS_INSUFFICIENT


def test_answer_status_partial_topic_requires_claims() -> None:
    # claims 가드: verified + partial_topic 이어도 claims 가 비면 partial 불가 →
    # supported 조건(claims)도 미충족, comparison 도 아님 → insufficient
    out = answer_status({}, [], True, [PARTIAL_TOPIC_GROUNDING_REASON])
    assert out == ANSWER_STATUS_INSUFFICIENT


# --- answer_query_type ---


def test_answer_query_type_insufficient_status_wins() -> None:
    # status=insufficient 면 query_type 과 무관하게 abstention
    assert (
        answer_query_type({"query_type": "comparison"}, ANSWER_STATUS_INSUFFICIENT)
        == "abstention"
    )


def test_answer_query_type_maps_known_types() -> None:
    assert answer_query_type({"query_type": "comparison"}, "answered") == "comparison"
    assert answer_query_type({"query_type": "follow_up"}, "answered") == "follow_up"


def test_answer_query_type_unknown_falls_back_to_single_doc() -> None:
    assert answer_query_type({"query_type": "single_doc"}, "answered") == "single_doc"
    assert answer_query_type({"query_type": "xyz"}, "answered") == "single_doc"
    assert answer_query_type({}, "answered") == "single_doc"
