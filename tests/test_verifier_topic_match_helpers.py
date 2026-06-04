"""Unit coverage for ``rag_verifier`` topic-grounding 헬퍼 2종.

partial-topic grounding 정책(issue #687/ADR 0004)과 single-doc grounding
가드(Phase 5 audit #1, issue #1008)의 핵심 카운팅 헬퍼다. topic 이 한 문서
안에서 grounded 되는지 vs combined-pool 에 흩어져 있는지를 구분하는 경계가
조용히 회귀하면 verifier_false_negative 가 재발한다. 특히:

- ``_count_target_doc_topic_matches`` 는 combined-pool 합산(cross-doc 흩어진
  topic 도 각각 카운트) + cross-entity 가드(``matched_doc_ids`` 비어있지 않은데
  target 매칭 evidence 가 없으면 0).
- ``_max_single_doc_topic_matches`` 는 per-doc 최대(cross-doc 흩어진 topic 은
  doc 당 1) — 같은 입력에서 ``_count`` 와 값이 갈리는 게 핵심 경계.

모든 기대값은 pristine 소스 실행으로 캡처했다.
``from rag_verifier import ...`` (repo root module).
"""

from __future__ import annotations

from typing import Any

import pytest

from rag_verifier import (
    _count_target_doc_topic_matches,
    _max_single_doc_topic_matches,
)

TOPICS = ["alpha", "beta"]


def _ev(doc_id: str, text: str) -> dict[str, Any]:
    return {"doc_id": doc_id, "text": text}


# ----------------------------------------------------------------------
# 핵심 구분: combined-pool 합산(_count) vs per-doc 최대(_max)
# ----------------------------------------------------------------------


def test_single_doc_both_topics_count_and_max_agree() -> None:
    # 한 문서에 두 topic → 둘 다 2.
    evidence = [_ev("d1", "alpha beta together")]
    assert _count_target_doc_topic_matches({}, evidence, TOPICS) == 2
    assert _max_single_doc_topic_matches({}, evidence, TOPICS) == 2


def test_cross_doc_spread_count_sums_but_max_caps_per_doc() -> None:
    # alpha@d1, beta@d2 로 흩어짐 → _count=2(합산), _max=1(doc 당 최대). 핵심 경계.
    evidence = [_ev("d1", "alpha only"), _ev("d2", "beta only")]
    assert _count_target_doc_topic_matches({}, evidence, TOPICS) == 2
    assert _max_single_doc_topic_matches({}, evidence, TOPICS) == 1


def test_same_doc_multi_chunk_grounds_within_one_doc() -> None:
    # 같은 doc_id 의 여러 chunk 는 한 문서로 합쳐져 grounding → _max=2.
    evidence = [_ev("d1", "alpha"), _ev("d1", "beta")]
    assert _count_target_doc_topic_matches({}, evidence, TOPICS) == 2
    assert _max_single_doc_topic_matches({}, evidence, TOPICS) == 2


# ----------------------------------------------------------------------
# cross-entity 가드 (matched_doc_ids 풀 제한)
# ----------------------------------------------------------------------


def test_constrained_to_target_doc_restricts_pool() -> None:
    # matched_doc_ids=["d1"] → d1 텍스트(alpha)만 카운트, d2(beta) 제외.
    analysis = {"matched_doc_ids": ["d1"]}
    evidence = [_ev("d1", "alpha only"), _ev("d2", "beta only")]
    assert _count_target_doc_topic_matches(analysis, evidence, TOPICS) == 1
    assert _max_single_doc_topic_matches(analysis, evidence, TOPICS) == 1


def test_constrained_no_matching_evidence_is_zero_guard() -> None:
    # target=dX 인데 evidence 에 dX 없음 → cross-entity 가드로 0.
    analysis = {"matched_doc_ids": ["dX"]}
    evidence = [_ev("d1", "alpha only"), _ev("d2", "beta only")]
    assert _count_target_doc_topic_matches(analysis, evidence, TOPICS) == 0
    assert _max_single_doc_topic_matches(analysis, evidence, TOPICS) == 0


def test_empty_matched_doc_ids_keeps_guard_dormant() -> None:
    # matched_doc_ids=[] (빈 리스트) → 가드 dormant, unconstrained 와 동일.
    analysis = {"matched_doc_ids": []}
    evidence = [_ev("d1", "alpha only"), _ev("d2", "beta only")]
    assert _count_target_doc_topic_matches(analysis, evidence, TOPICS) == 2
    assert _max_single_doc_topic_matches(analysis, evidence, TOPICS) == 1


# ----------------------------------------------------------------------
# degenerate 입력 + 부분문자열 매칭
# ----------------------------------------------------------------------


@pytest.mark.parametrize("topics", [[], ["gamma"]])
def test_no_topic_match_is_zero(topics: list[str]) -> None:
    # 빈 topic 또는 매칭 없는 topic → 0.
    evidence = [_ev("d1", "alpha beta")]
    assert _count_target_doc_topic_matches({}, evidence, topics) == 0
    assert _max_single_doc_topic_matches({}, evidence, topics) == 0


def test_empty_evidence_is_zero() -> None:
    assert _count_target_doc_topic_matches({}, [], TOPICS) == 0
    assert _max_single_doc_topic_matches({}, [], TOPICS) == 0


def test_topic_matches_as_substring() -> None:
    # form 은 부분문자열로 매칭된다("alph" ⊂ "alpha only").
    evidence = [_ev("d1", "alpha only")]
    assert _count_target_doc_topic_matches({}, evidence, ["alph"]) == 1


def test_topic_matches_via_canonical_normalization() -> None:
    # normalize_text("5천만원") == "50000000": form 이 raw text 엔 없어도 canonical
    # 형태에 있으면 매칭(둘 다 `form in pool_text OR form in pool_canonical`).
    # 이 normalization grounding 경로는 ASCII-only 테스트로는 덮이지 않는다.
    evidence = [_ev("d1", "5천만원")]
    assert _count_target_doc_topic_matches({}, evidence, ["50000000"]) == 1
    assert _max_single_doc_topic_matches({}, evidence, ["50000000"]) == 1


def test_none_matched_doc_ids_keeps_guard_dormant() -> None:
    # 명시적 None(부재가 아님)도 `or []` 로 dormant 처리 — unconstrained 와 동일.
    analysis = {"matched_doc_ids": None}
    evidence = [_ev("d1", "alpha only"), _ev("d2", "beta only")]
    assert _count_target_doc_topic_matches(analysis, evidence, TOPICS) == 2
    assert _max_single_doc_topic_matches(analysis, evidence, TOPICS) == 1
