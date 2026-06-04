"""Unit coverage for rag_query.make_plan stage 선택 + metadata_filters 결정 (issue #2377).

``make_plan``(rag_query.py:479)의 ``filter_stage``/``relaxed``/``metadata_filters``
결정 로직이 직접 단위 테스트가 0건이었다. import-safe leaf(rag_core/torch/chromadb
미로드, ADR 0045). #2368(validation)·#2371(strategy) 후속, stage/filter 선택 한
concern 한정. test-only, 소스 무수정.

핵심 변별:
- 기본 strict / relaxed=True · metadata_first=False → relaxed.
- relaxed stage → metadata_filters 비움.
- by_stage 제공 시 우선, 부재 시 entities → agencies fallback.
"""
from __future__ import annotations

from rag_query import make_plan

_A = {"query_type": "single_doc"}


def test_default_stage_is_strict_not_relaxed() -> None:
    plan = make_plan(_A)
    assert plan["filter_stage"] == "strict"
    assert plan["relaxed"] is False


def test_relaxed_flag_forces_relaxed_stage_and_clears_filters() -> None:
    plan = make_plan(_A, relaxed=True)
    assert plan["filter_stage"] == "relaxed"
    assert plan["relaxed"] is True
    # relaxed stage 는 metadata_filters 를 비운다(strict 분기와 구분).
    assert plan["metadata_filters"] == {}


def test_metadata_first_false_also_forces_relaxed() -> None:
    # metadata_first=False 도 relaxed stage 로 강제(relaxed flag 와 독립 경로).
    plan = make_plan(_A, metadata_first=False)
    assert plan["filter_stage"] == "relaxed"
    assert plan["relaxed"] is True


def test_filters_fall_back_to_entities_as_agencies() -> None:
    # by_stage 없고 명시 필터 없으면 entities 를 agencies 필터로 폴백.
    plan = make_plan({"query_type": "single_doc", "entities": ["기관 A", "기관 B"]})
    assert plan["metadata_filters"] == {"agencies": ["기관 A", "기관 B"]}


def test_stage_specific_filters_take_precedence_over_entities() -> None:
    # metadata_filters_by_stage[stage] 가 있으면 그것을 쓴다 — entities fallback 으로
    # 떨어지지 않는다(precedence 역전 mutation 을 KILL).
    plan = make_plan({
        "query_type": "single_doc",
        "entities": ["기관 IGNORED"],
        "metadata_filters_by_stage": {"strict": {"agencies": ["X"]}},
    })
    assert plan["metadata_filters"] == {"agencies": ["X"]}


def test_reduced_stage_reads_its_own_by_stage_filters() -> None:
    # stage="reduced"(strict/relaxed 아닌 non-relaxed 경로) → by_stage 의 그 stage 키를
    # 정확히 조회. get(stage) 를 "strict" 로 하드코딩하거나 reduced 분기를 무력화하면 KILL.
    plan = make_plan(
        {
            "query_type": "single_doc",
            "metadata_filters_by_stage": {"reduced": {"agencies": ["R"]}, "strict": {"agencies": ["S"]}},
        },
        stage="reduced",
    )
    assert plan["filter_stage"] == "reduced"
    assert plan["metadata_filters"] == {"agencies": ["R"]}


def test_reduced_stage_entities_fallback_not_strict_only() -> None:
    # by_stage 부재 시 entities fallback 은 strict 뿐 아니라 reduced stage 에서도 동작한다.
    # fallback 을 stage=="strict" 로 한정하는 mutation 을 KILL.
    plan = make_plan({"query_type": "single_doc", "entities": ["기관 A"]}, stage="reduced")
    assert plan["metadata_filters"] == {"agencies": ["기관 A"]}
