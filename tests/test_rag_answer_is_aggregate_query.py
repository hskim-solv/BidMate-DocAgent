"""Unit coverage for rag_answer._is_aggregate_query 집계 의도 탐지 (issue #2392).

``_is_aggregate_query``(rag_answer.py:528)는 "모든/전체/정리" 등 집계 의도 시그널을
``resolved_query``(substring)와 ``tokens``(exact membership) 두 채널로 탐지하는 순수
import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위 테스트가
0건이었다. test-only, 소스 무수정.

핵심 변별:
- resolved_query 채널은 substring(`sig in resolved`) — 시그널이 더 큰 문자열에 임베드돼도 매칭.
- tokens 채널은 exact membership(`sig in tokens`) — 시그널을 substring 으로만 포함하는 토큰은 미매칭.
- 두 채널 OR; 시그널 없음/키 부재 → False.
"""
from __future__ import annotations

from rag_answer import _is_aggregate_query


def test_resolved_query_substring_channel() -> None:
    # resolved_query 안에 시그널이 substring 으로 있으면 True.
    assert _is_aggregate_query({"resolved_query": "모든 항목을 정리해줘", "tokens": []}) is True
    # 시그널이 더 긴 어절에 임베드돼도(substring) 매칭 — '전체' ⊂ '전체적으로'.
    assert _is_aggregate_query({"resolved_query": "전체적으로 보면", "tokens": []}) is True


def test_tokens_exact_membership_channel() -> None:
    # tokens 에 시그널이 정확히 한 원소로 있으면 True(resolved 비어도).
    assert _is_aggregate_query({"resolved_query": "", "tokens": ["전체"]}) is True
    # 시그널 아닌 토큰만 → False.
    assert _is_aggregate_query({"resolved_query": "", "tokens": ["예산", "기간"]}) is False


def test_tokens_channel_is_membership_not_substring() -> None:
    # 토큰 '전체적' 은 시그널 '전체' 를 substring 으로 포함하지만 exact 원소가 아니므로
    # tokens 채널에서는 매칭되지 않는다(membership 의미 pin).
    assert _is_aggregate_query({"resolved_query": "", "tokens": ["전체적"]}) is False
    # 동일 문자열을 resolved 로 주면 substring 채널로 매칭 → True(두 채널 의미 차이 pin).
    assert _is_aggregate_query({"resolved_query": "전체적", "tokens": []}) is True


def test_no_signal_or_empty_analysis_is_false() -> None:
    # 어느 채널에도 시그널 없음 → False.
    assert _is_aggregate_query({"resolved_query": "예산은 얼마인가?", "tokens": ["예산은", "얼마인가"]}) is False
    # 키 부재(빈 analysis) → False(None 폴백).
    assert _is_aggregate_query({}) is False


def test_all_aggregate_signals_individually_detected() -> None:
    # frozenset 9종 전부 개별 pin — 소스에서 어느 하나라도 드롭되면 그 케이스가 KILL.
    # (frozenset 을 순회하면 mutant 와 함께 움직여 vacuous 가 되므로 시그널 리터럴을 하드코딩.)
    for sig in ("나열", "리스트", "모두", "모든", "목록", "일체", "전부", "전체", "정리"):
        assert _is_aggregate_query({"resolved_query": f"{sig} 보여줘", "tokens": []}) is True
    # 시그널이 아닌 유사어는 탐지되지 않음.
    assert _is_aggregate_query({"resolved_query": "요약 보여줘", "tokens": []}) is False
