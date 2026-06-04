"""Unit coverage for rag_retrieval.apply_comparison_balance (issue #2281).

``apply_comparison_balance`` 는 comparison 쿼리에서 target(doc_id/agency)별
coverage 를 보장하는 top-k 컷이다(ADR 0058 hybrid 의 일부). 직접 단위
테스트가 없어 early-return no-op·disabled 글로벌 컷·enabled min_per_target
보장·effective_min clamp·최종 정렬·target_field 분기가 조용히 깨질 수 있었다
(test-only, 소스 무수정).

leaf 모듈(rag_core back-edge 0 = ADR 0045; ``comparison_targets_for_analysis``
는 rag_query, ``_coverage_counts`` 는 같은 모듈). 핵심 변별: **동일
fixture/top_k 에서 disabled 는 저-score target 을 누락(after=0)하지만 enabled
는 ``min_per_target`` 으로 포함(after=1)** — 단순 ``scored[:top_k]`` 와 구별되는
balance 메커니즘을 못 박는다. negative assertion 으로 early-return 무기록·
balanced 플래그·clamp 값·정렬 방향·target_field 를 고정한다.
"""
from __future__ import annotations

from typing import Any

from rag_retrieval import apply_comparison_balance


def _sc(chunk_id: str, score: float, **extra: Any) -> dict[str, Any]:
    return {"chunk_id": chunk_id, "score": score, **extra}


def _two_doc_pool() -> list[dict[str, Any]]:
    # A 2개(0.9/0.8) + B 1개(0.1). 글로벌 top-2 는 B 를 누락한다(저-score).
    return [
        _sc("a1", 0.9, doc_id="A"),
        _sc("a2", 0.8, doc_id="A"),
        _sc("b1", 0.1, doc_id="B"),
    ]


def _comparison(matched: list[str]) -> dict[str, Any]:
    return {"query_type": "comparison", "matched_doc_ids": matched}


def test_non_comparison_query_is_noop_without_recording() -> None:
    # query_type 이 comparison 이 아니면 즉시 scored[:top_k] 반환, plan 무기록.
    plan: dict[str, Any] = {}
    out = apply_comparison_balance(
        [_sc("a", 0.9), _sc("b", 0.5)], {"query_type": "factual"}, plan, 1
    )
    assert [i["chunk_id"] for i in out] == ["a"]
    # early-return 메커니즘 pin: comparison_coverage 를 기록하지 않는다.
    assert "comparison_coverage" not in plan


def test_single_target_comparison_is_noop_without_recording() -> None:
    # comparison 이어도 target<2 면 is_comparison False → no-op + 무기록.
    plan: dict[str, Any] = {}
    out = apply_comparison_balance(
        [_sc("a", 0.9, doc_id="A")], _comparison(["A"]), plan, 5
    )
    assert [i["chunk_id"] for i in out] == ["a"]
    assert "comparison_coverage" not in plan


def test_disabled_returns_global_topk_and_drops_low_target() -> None:
    # comparison_balance 미설정 → 글로벌 scored[:top_k]. B(저-score)는 누락.
    plan: dict[str, Any] = {}
    out = apply_comparison_balance(_two_doc_pool(), _comparison(["A", "B"]), plan, 2)
    assert [i["chunk_id"] for i in out] == ["a1", "a2"]  # B 없음
    cov = plan["comparison_coverage"]
    assert cov["balanced"] is False
    assert cov["after"]["B"] == 0  # disabled 는 저-score target 을 보장하지 않는다
    # before 는 top_k 컷 전 전체 pool 분포(컷 후 값으로 바뀌면 KILL).
    assert cov["before"] == {"A": 2, "B": 1}


def test_enabled_guarantees_underrepresented_target() -> None:
    # enabled → min_per_target=1 이 B(0.1)를 저-score 임에도 결과에 포함시킨다.
    plan: dict[str, Any] = {"comparison_balance": {"enabled": True, "min_per_target": 1}}
    out = apply_comparison_balance(_two_doc_pool(), _comparison(["A", "B"]), plan, 2)
    assert [i["chunk_id"] for i in out] == ["a1", "b1"]  # a2 대신 b1 보장
    cov = plan["comparison_coverage"]
    assert cov["balanced"] is True
    assert cov["after"] == {"A": 1, "B": 1}  # 각 target 1개씩 균형


def test_enabled_and_disabled_diverge_on_identical_pool() -> None:
    # 동일 scored/top_k: 오직 enabled 플래그만 결과를 바꾼다(balance 메커니즘이
    # 실재함을 직접 대비). disabled after.B==0, enabled after.B==1.
    pool = _two_doc_pool()
    analysis = _comparison(["A", "B"])
    plan_off: dict[str, Any] = {}
    plan_on: dict[str, Any] = {
        "comparison_balance": {"enabled": True, "min_per_target": 1}
    }
    apply_comparison_balance(pool, analysis, plan_off, 2)
    apply_comparison_balance(pool, analysis, plan_on, 2)
    assert plan_off["comparison_coverage"]["after"]["B"] == 0
    assert plan_on["comparison_coverage"]["after"]["B"] == 1


def test_effective_min_clamped_when_over_requested() -> None:
    # min_per_target=5 지만 top_k=2 / 2 targets → max_min = 2//2 = 1 로 clamp.
    plan: dict[str, Any] = {"comparison_balance": {"enabled": True, "min_per_target": 5}}
    out = apply_comparison_balance(_two_doc_pool(), _comparison(["A", "B"]), plan, 2)
    assert plan["comparison_coverage"]["min_per_target"] == 1  # 5 가 아니라 clamp 된 1
    assert [i["chunk_id"] for i in out] == ["a1", "b1"]


def test_effective_min_scales_with_topk_budget() -> None:
    # top_k=4 / 2 targets → max_min = 4//2 = 2. min_per_target=5 는 2 로 clamp.
    plan: dict[str, Any] = {"comparison_balance": {"enabled": True, "min_per_target": 5}}
    pool = [
        _sc("a1", 0.9, doc_id="A"),
        _sc("a2", 0.8, doc_id="A"),
        _sc("a3", 0.7, doc_id="A"),
        _sc("b1", 0.1, doc_id="B"),
    ]
    out = apply_comparison_balance(pool, _comparison(["A", "B"]), plan, 4)
    assert plan["comparison_coverage"]["min_per_target"] == 2  # budget 따라 1→2
    assert sorted(i["chunk_id"] for i in out) == ["a1", "a2", "a3", "b1"]


def test_final_selection_sorted_by_score_descending() -> None:
    # B target 이 더 높은 score(0.9). selection 은 target 순서(A 먼저)로 채워지지만
    # 최종 출력은 score 내림차순 → [b, a]. 정렬을 제거하면 [a, b] 로 KILL.
    plan: dict[str, Any] = {"comparison_balance": {"enabled": True, "min_per_target": 1}}
    pool = [_sc("a", 0.3, doc_id="A"), _sc("b", 0.9, doc_id="B")]
    out = apply_comparison_balance(pool, _comparison(["A", "B"]), plan, 2)
    assert [i["chunk_id"] for i in out] == ["b", "a"]  # selection 순서 [a,b] 가 아님


def test_agency_fallback_when_no_doc_ids() -> None:
    # matched_doc_ids 없고 entities>=2 → target_field 가 agency 로 분기.
    plan: dict[str, Any] = {"comparison_balance": {"enabled": True, "min_per_target": 1}}
    pool = [
        _sc("x", 0.9, agency="기관A"),
        _sc("y", 0.8, agency="기관A"),
        _sc("z", 0.1, agency="기관B"),
    ]
    analysis = {"query_type": "comparison", "entities": ["기관A", "기관B"]}
    out = apply_comparison_balance(pool, analysis, plan, 2)
    cov = plan["comparison_coverage"]
    assert cov["target_field"] == "agency"  # doc_id 가 아님
    assert [i["chunk_id"] for i in out] == ["x", "z"]  # 저-score 기관B 도 보장
    assert cov["after"] == {"기관A": 1, "기관B": 1}
