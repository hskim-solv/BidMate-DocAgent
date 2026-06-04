"""Unit coverage for rag_answer.build_insufficiency 진단 dict (issue #2400).

``build_insufficiency``(rag_answer.py:423)는 보류(abstention) 응답의 진단 dict 를
빌드하는 순수 import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접
단위 테스트가 0건이었다. 외부 dep ``specific_topics`` 는 빈 analysis 로 ``[]`` 고정해
타깃 자체 로직만 격리 검증한다. test-only, 소스 무수정.

핵심 변별:
- missing_targets = checked_entities − claims target 집합(set 차집합).
- re-fill 분기는 ``not verified`` 일 때만(verified 면 미실행).
- checked_entities = entities → context_entities → [] 폴백(entities 우선).
- reasons 3-tier: 주어진 verification_reasons → ["verification_failed"](not verified) → [].
"""
from __future__ import annotations

from typing import Any

from rag_answer import build_insufficiency

_SUPPORTED_A: list[dict[str, Any]] = [{"target": "기관A", "claim": "x"}]


def test_missing_targets_set_difference_and_doc_ids() -> None:
    out = build_insufficiency(
        "예산은?",
        {"entities": ["기관A", "기관B"], "matched_doc_ids": ["d1"]},
        _SUPPORTED_A,  # 기관A 만 지지.
        True,
        [],
    )
    # 지지되지 않은 기관B 만 missing(set 차집합).
    assert out["missing_targets"] == ["기관B"]
    assert "기관A" not in out["missing_targets"]
    # checked_doc_ids 는 matched_doc_ids 그대로.
    assert out["checked_doc_ids"] == ["d1"]
    # matched_doc_ids 키 부재 시 빈 리스트로 폴백(`or []` — None 누출 차단, 보류 dict 의 흔한 경로).
    assert build_insufficiency("q", {}, [], True, [])["checked_doc_ids"] == []
    # message 는 query 보간 고정 문구.
    assert out["message"] == "'예산은?'에 대한 충분한 근거를 찾지 못했습니다."


def test_refill_missing_targets_only_when_not_verified() -> None:
    analysis = {"entities": ["기관A"]}
    # not verified + missing 없음(전부 지지) + checked 있음 → 전체 checked 로 re-fill.
    unverified = build_insufficiency("q", analysis, _SUPPORTED_A, False, [])
    assert unverified["missing_targets"] == ["기관A"]
    # verified 면 동일 조건이라도 re-fill 안 함(`not verified` 가드) → missing 빈 채로.
    verified = build_insufficiency("q", analysis, _SUPPORTED_A, True, [])
    assert verified["missing_targets"] == []


def test_checked_entities_entities_then_context_then_empty() -> None:
    # entities 우선(둘 다 있어도 entities).
    both = build_insufficiency("q", {"entities": ["기관A"], "context_entities": ["기관Z"]}, [], True, [])
    assert both["checked_entities"] == ["기관A"]
    # entities 없으면 context_entities 폴백.
    ctx = build_insufficiency("q", {"context_entities": ["기관C"]}, [], True, [])
    assert ctx["checked_entities"] == ["기관C"]
    # 둘 다 없으면 [].
    empty = build_insufficiency("q", {}, [], True, [])
    assert empty["checked_entities"] == []


def test_reasons_three_tier() -> None:
    # 주어진 verification_reasons 우선(not verified 라도 그대로).
    assert build_insufficiency("q", {}, [], False, ["custom"])["reasons"] == ["custom"]
    # 비어 있고 not verified → ["verification_failed"].
    assert build_insufficiency("q", {}, [], False, [])["reasons"] == ["verification_failed"]
    # 비어 있고 verified → [].
    assert build_insufficiency("q", {}, [], True, [])["reasons"] == []
