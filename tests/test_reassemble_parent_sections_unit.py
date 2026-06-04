"""Unit coverage for rag_retrieval.reassemble_parent_sections (issue #2275).

``reassemble_parent_sections`` 는 hierarchical 검색에서 child chunk 를 parent
section 으로 재조립한다. 직접 단위 테스트가 없어(parent 그룹핑·best-score
선택·child 수집·sort·top_k 컷·plan side-effect) 조용히 깨질 수 있었다
(test-only, 소스 무수정).

``analysis=None`` 순수 경로만 다룬다(``apply_comparison_balance`` 위임 회피).
regions/page_span 없는 fixture 로 ``normalize_*`` 병합 분기도 회피. leaf
모듈(rag_core back-edge 0 = ADR 0045). negative assertion 으로 best-score
선택·정렬 방향·top_k 컷·plan count(컷 전 전체)·병합 방향을 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_retrieval import reassemble_parent_sections


def _chunk(chunk_id: str, score: float, **extra: Any) -> dict[str, Any]:
    return {"chunk_id": chunk_id, "score": score, **extra}


def test_empty_chunks_returns_empty_and_zero_count() -> None:
    plan: dict[str, Any] = {}
    out = reassemble_parent_sections({"parent_sections": []}, [], 5, plan, None)
    assert out == []
    assert plan["parent_candidate_count"] == 0


def test_missing_parent_uses_hierarchical_fallback() -> None:
    # parent_sections 에 매칭 parent 가 없으면 fallback 모드 + child_chunk_ids 보존
    plan: dict[str, Any] = {}
    chunks = [_chunk("ch1", 0.9, parent_section_id="p1", text="자식 본문")]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 5, plan, None)
    assert out[0]["retrieval_mode"] == "hierarchical_fallback"
    assert out[0]["child_chunk_ids"] == ["ch1"]


def test_present_parent_merges_parent_fields() -> None:
    # parent 존재 → hierarchical 모드 + section/text 는 parent 것(child 것 아님)
    plan: dict[str, Any] = {}
    index = {"parent_sections": [{"section_id": "p1", "section": "부모섹션", "text": "부모 본문"}]}
    chunks = [_chunk("ch1", 0.9, parent_section_id="p1", section="자식섹션", text="자식 본문")]
    out = reassemble_parent_sections(index, chunks, 5, plan, None)
    assert out[0]["retrieval_mode"] == "hierarchical"
    assert out[0]["section"] == "부모섹션"  # child 의 '자식섹션' 이 아님 → 병합 방향 pin
    assert out[0]["text"] == "부모 본문"


def test_best_scoring_chunk_wins_per_parent() -> None:
    # 같은 parent 의 여러 chunk 중 최고 score 가 대표가 된다(낮은 score 선택 mutant KILL)
    plan: dict[str, Any] = {}
    chunks = [
        _chunk("low", 0.3, parent_section_id="p1"),
        _chunk("high", 0.9, parent_section_id="p1"),
        _chunk("mid", 0.5, parent_section_id="p1"),
    ]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 5, plan, None)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "high"
    assert out[0]["score"] == 0.9


def test_all_children_collected_under_parent() -> None:
    # best 가 아닌 chunk 도 child_chunk_ids 에 전부 모인다(best 만 수집 mutant KILL)
    plan: dict[str, Any] = {}
    chunks = [
        _chunk("c1", 0.3, parent_section_id="p1"),
        _chunk("c2", 0.9, parent_section_id="p1"),
    ]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 5, plan, None)
    assert sorted(out[0]["child_chunk_ids"]) == ["c1", "c2"]


def test_results_sorted_by_score_descending() -> None:
    # 서로 다른 parent → score 내림차순 정렬(asc/무정렬 mutant KILL)
    plan: dict[str, Any] = {}
    chunks = [
        _chunk("a", 0.3, parent_section_id="pA"),
        _chunk("b", 0.9, parent_section_id="pB"),
        _chunk("c", 0.6, parent_section_id="pC"),
    ]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 5, plan, None)
    assert [i["chunk_id"] for i in out] == ["b", "c", "a"]


def test_top_k_truncates_after_sort() -> None:
    # top_k 컷은 정렬 후 적용 → 상위 2개만
    plan: dict[str, Any] = {}
    chunks = [
        _chunk("a", 0.3, parent_section_id="pA"),
        _chunk("b", 0.9, parent_section_id="pB"),
        _chunk("c", 0.6, parent_section_id="pC"),
    ]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 2, plan, None)
    assert [i["chunk_id"] for i in out] == ["b", "c"]


def test_parent_candidate_count_is_pre_truncation_total() -> None:
    # plan["parent_candidate_count"] 는 top_k 컷 전 전체 parent 수.
    # 컷 후 길이(2)로 바꾸면 KILL — top_k=2 인데 parent 3개라 count=3 이어야 한다.
    plan: dict[str, Any] = {}
    chunks = [
        _chunk("a", 0.3, parent_section_id="pA"),
        _chunk("b", 0.9, parent_section_id="pB"),
        _chunk("c", 0.6, parent_section_id="pC"),
    ]
    out = reassemble_parent_sections({"parent_sections": []}, chunks, 2, plan, None)
    assert len(out) == 2
    assert plan["parent_candidate_count"] == 3


def test_parent_id_falls_back_to_section_id() -> None:
    # parent_section_id 부재 시 section_id 로 parent 를 찾는다(우선순위 분기)
    plan: dict[str, Any] = {}
    index = {"parent_sections": [{"section_id": "sX", "section": "섹션X", "text": "본문X"}]}
    chunks = [_chunk("x", 0.5, section_id="sX")]  # parent_section_id 없음
    out = reassemble_parent_sections(index, chunks, 5, plan, None)
    assert out[0]["retrieval_mode"] == "hierarchical"
    assert out[0]["section"] == "섹션X"
