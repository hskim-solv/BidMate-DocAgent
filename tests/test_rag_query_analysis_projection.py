"""Unit coverage for rag_query analysis→계획 파라미터/요약 투영 helper (issue #2347).

``comparison_targets_for_analysis`` / ``summarize_metadata_match`` /
``query_type_default_top_k`` 은 analysis dict 를 계획 단계 파라미터로 투영하는
import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위 테스트가
0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``comparison_targets_for_analysis`` — doc_ids≥2 우선("doc_id"), 아니면
  entities≥2("agency"), 아니면 ([],"").
- ``summarize_metadata_match`` — 9-key 고정 스키마 투영(미지 key drop, 누락→기본값).
- ``query_type_default_top_k`` — 매핑, 미지 query_type → single_doc(=4).
"""
from __future__ import annotations

from rag_query import (
    comparison_targets_for_analysis,
    query_type_default_top_k,
    summarize_metadata_match,
)


# ---- comparison_targets_for_analysis ----

def test_comparison_targets_prefers_doc_ids_when_two_or_more() -> None:
    # matched_doc_ids ≥2 → (ordered_unique, "doc_id"); entities 가 있어도 doc_id 우선.
    targets, field = comparison_targets_for_analysis(
        {"matched_doc_ids": ["d1", "d2", "d1"], "entities": ["e1", "e2"]}
    )
    assert targets == ["d1", "d2"] and field == "doc_id"


def test_comparison_targets_falls_back_to_agencies() -> None:
    # doc_ids < 2 → entities ≥2 → (ordered_unique, "agency").
    result = comparison_targets_for_analysis({"matched_doc_ids": ["d1"], "entities": ["e1", "e2", "e1"]})
    assert result == (["e1", "e2"], "agency")


def test_comparison_targets_empty_when_not_applicable() -> None:
    # 양쪽 모두 <2 → ([], "").
    assert comparison_targets_for_analysis({}) == ([], "")
    assert comparison_targets_for_analysis({"entities": ["e1"]}) == ([], "")


# ---- summarize_metadata_match ----

def test_summarize_metadata_match_projects_fixed_schema() -> None:
    full = {
        "doc_id": "D", "field": "f", "value": "v", "agency": "A", "project": "P",
        "confidence": 0.9, "stage": "strict", "match_type": "exact",
        "matched_terms": ["t"], "EXTRA": "dropped",
    }
    out = summarize_metadata_match(full)
    assert out == {
        "doc_id": "D", "field": "f", "value": "v", "agency": "A", "project": "P",
        "confidence": 0.9, "stage": "strict", "match_type": "exact", "matched_terms": ["t"],
    }
    # 스키마 밖 key(EXTRA) 는 투영에서 제외.
    assert "EXTRA" not in out


def test_summarize_metadata_match_defaults_on_missing() -> None:
    out = summarize_metadata_match({})
    # 7개 문자열 key 의 기본값은 모두 "" — 하나라도 다른 default("X" 등)면 KILL.
    # (key-set 동등성만으론 default 변경을 못 잡으므로 값까지 전부 고정한다.)
    assert all(
        out[k] == ""
        for k in ("doc_id", "field", "value", "agency", "project", "stage", "match_type")
    )
    # confidence/matched_terms 는 타입별 기본값.
    assert out["confidence"] == 0.0 and out["matched_terms"] == []
    # 9-key 가 모두 존재(스키마 고정).
    assert set(out) == {
        "doc_id", "field", "value", "agency", "project",
        "confidence", "stage", "match_type", "matched_terms",
    }


# ---- query_type_default_top_k ----

def test_query_type_default_top_k_maps_known_types() -> None:
    assert query_type_default_top_k("single_doc") == 4
    assert query_type_default_top_k("comparison") == 6


def test_query_type_default_top_k_unknown_falls_back_to_single_doc() -> None:
    # 미지 query_type → single_doc 기본값(=4), KeyError 아님.
    assert query_type_default_top_k("unknown_xyz") == 4
