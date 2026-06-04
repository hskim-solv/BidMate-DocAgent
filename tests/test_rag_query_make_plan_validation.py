"""Unit coverage for rag_query.make_plan 입력 검증 + top_k budget 출처 (issue #2368).

``make_plan`` 은 analysis dict 를 검색 계획 dict 로 투영하는 import-safe leaf
(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위 테스트가 0건이었다.
본 파일은 **입력 검증 가드 + top_k budget 출처** 한 concern 으로 한정한다
(scoring/stage/filters 빌드 로직은 후속). test-only, 소스 무수정.

핵심 변별:
- retrieval_mode/backend, rrf_k 범위, bm25 3종 파라미터가 허용 집합 밖이면 ValueError.
  ``match=`` 로 *올바른 필드*의 메시지인지까지 고정(다른 필드 메시지로
  cross-wiring 되는 mutation 차단).
- rrf_k 경계(1, 1000)는 통과(off-by-one mutation 차단).
- retrieval_budget.reason 이 top_k/top_k_reason 출처를 반영.
"""
from __future__ import annotations

import pytest

from rag_query import make_plan

_ANALYSIS = {"query_type": "single_doc"}


def test_valid_minimal_plan_uses_query_type_defaults() -> None:
    # 유효 기본 입력 → query_type 기본 top_k(=4), budget reason=default, strict stage.
    plan = make_plan(_ANALYSIS)
    assert plan["top_k"] == 4
    assert plan["retrieval_budget"]["reason"] == "single_doc_default"
    assert plan["filter_stage"] == "strict"


def test_rejects_invalid_retrieval_mode() -> None:
    # VALID_RETRIEVAL_MODES 밖 → ValueError(가드 제거/메시지 cross-wiring 시 KILL).
    with pytest.raises(ValueError, match="retrieval_mode"):
        make_plan(_ANALYSIS, retrieval_mode="BOGUS")


def test_rejects_invalid_retrieval_backend() -> None:
    with pytest.raises(ValueError, match="retrieval_backend"):
        make_plan(_ANALYSIS, retrieval_backend="BOGUS")


def test_rrf_k_range_boundaries() -> None:
    # 경계 1, 1000 은 통과 — 비교 < / > 가 <= / >= 로 바뀌면(off-by-one) KILL.
    assert make_plan(_ANALYSIS, rrf_k=1)["rrf_k"] == 1
    assert make_plan(_ANALYSIS, rrf_k=1000)["rrf_k"] == 1000
    # 범위 밖(0, 1001) → ValueError(범위 가드 제거 시 KILL).
    with pytest.raises(ValueError, match="rrf_k"):
        make_plan(_ANALYSIS, rrf_k=0)
    with pytest.raises(ValueError, match="rrf_k"):
        make_plan(_ANALYSIS, rrf_k=1001)


def test_rejects_invalid_bm25_params() -> None:
    # 3개 bm25 파라미터 각각이 독립적으로 검증된다 — 한 가드라도 빠지면 그 줄이 KILL.
    # match= 로 각 가드가 자기 필드 메시지를 내는지까지 pin.
    with pytest.raises(ValueError, match="bm25_stopword_profile"):
        make_plan(_ANALYSIS, bm25_stopword_profile="BOGUS")
    with pytest.raises(ValueError, match="bm25_tokenizer"):
        make_plan(_ANALYSIS, bm25_tokenizer="BOGUS")
    with pytest.raises(ValueError, match="bm25_backend"):
        make_plan(_ANALYSIS, bm25_backend="BOGUS")


def test_budget_reason_reflects_top_k_source() -> None:
    # 명시 top_k → explicit_override.
    assert make_plan(_ANALYSIS, top_k=9)["retrieval_budget"]["reason"] == "explicit_override"
    # top_k_reason 명시 → 그대로 우선(top_k 없어도 default 로 떨어지지 않는다).
    assert (
        make_plan(_ANALYSIS, top_k_reason="custom_reason")["retrieval_budget"]["reason"]
        == "custom_reason"
    )
    # 둘 다 없음 → "{query_type}_default".
    assert make_plan(_ANALYSIS)["retrieval_budget"]["reason"] == "single_doc_default"
