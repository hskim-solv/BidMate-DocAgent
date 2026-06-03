"""Unit coverage for rag_metadata_processing.py match post-processing (issue #2173).

#2168 follow-up. ``rag_metadata_processing.py`` 의 순수 match 결과 후처리 함수
6종의 동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정). target 구성
(``make_metadata_target``/aliases)과 difflib 매칭(``match_metadata_target``/
``best_metadata_phrase_similarity``)은 각각 별도 concern → follow-up.

- ``make_metadata_match`` — match dict + stage strict/reduced 판정
  (STRICT=0.90 / REDUCED=0.70 경계), confidence round(3), matched_terms dedup
- ``dedupe_metadata_matches`` — (doc_id,field,value) 키별 max confidence + 정렬
- ``metadata_matches_for_stage`` — strict(≥0.90)/reduced(≥0.70)/기타 필터
- ``metadata_filters_from_matches`` — doc_ids/agencies/projects/confidence 집계(빈→{})
- ``best_metadata_doc_scores`` — doc_id별 max confidence(빈 doc_id 스킵)
- ``metadata_ambiguity_details`` — comparison/no_reduced/single/close/clear 분기

leaf 모듈(rag_text_processing/rag_conversation_state/korean_lexicon + stdlib 만
의존, rag_core back-edge 0 = ADR 0045 보존). negative assertion 으로 dedup/필터/
경계 판정이 실제로 일어나는지(non-vacuous) 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_metadata_processing import (
    best_metadata_doc_scores,
    dedupe_metadata_matches,
    make_metadata_match,
    metadata_ambiguity_details,
    metadata_filters_from_matches,
    metadata_matches_for_stage,
)


def _target(doc_id: str = "d1", field: str = "agency") -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "agency": "행안부",
        "project": "사업A",
        "field": field,
        "value": "행정안전부",
    }


def _match(doc_id: str, confidence: float, field: str = "agency", value: str = "v") -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "field": field,
        "value": value,
        "confidence": confidence,
        "agency": "A",
        "project": "P",
    }


# --- make_metadata_match ---


def test_make_metadata_match_strict_at_threshold() -> None:
    # STRICT=0.90 경계는 >= 라서 0.90 도 strict
    assert make_metadata_match(_target(), 0.90, "compact_contains", ["x"])["stage"] == "strict"


def test_make_metadata_match_reduced_below_threshold() -> None:
    assert make_metadata_match(_target(), 0.89, "fuzzy", ["x"])["stage"] == "reduced"


def test_make_metadata_match_rounds_confidence_and_dedups_terms() -> None:
    out = make_metadata_match(_target(), 0.123456, "t", ["행정", "행정", "안전"])
    assert out["confidence"] == 0.123  # round(3)
    assert out["matched_terms"] == ["행정", "안전"]  # ordered_unique 로 중복 제거


def test_make_metadata_match_carries_target_fields() -> None:
    out = make_metadata_match(_target("dX", "project"), 0.95, "compact_contains", ["v"])
    assert out["doc_id"] == "dX"
    assert out["field"] == "project"
    assert out["match_type"] == "compact_contains"


# --- dedupe_metadata_matches ---


def test_dedupe_keeps_highest_confidence_per_key() -> None:
    out = dedupe_metadata_matches([_match("d1", 0.7), _match("d1", 0.9)])
    assert [m["confidence"] for m in out] == [0.9]
    assert 0.7 not in [m["confidence"] for m in out]  # 낮은 중복은 버려진다


def test_dedupe_preserves_distinct_keys_sorted_desc() -> None:
    out = dedupe_metadata_matches([_match("d2", 0.7), _match("d1", 0.9)])
    assert [(m["doc_id"], m["confidence"]) for m in out] == [("d1", 0.9), ("d2", 0.7)]


# --- metadata_matches_for_stage ---


def test_metadata_matches_for_stage_strict_filters_below_090() -> None:
    # 경계값 0.90 은 포함(>=)되고 0.75 는 제외 — 임계값과 부등호를 동시에 고정
    ms = [_match("d1", 0.95), _match("d3", 0.90), _match("d2", 0.75)]
    assert [m["doc_id"] for m in metadata_matches_for_stage(ms, "strict")] == ["d1", "d3"]


def test_metadata_matches_for_stage_reduced_keeps_above_070() -> None:
    ms = [_match("d1", 0.95), _match("d2", 0.75)]
    assert [m["doc_id"] for m in metadata_matches_for_stage(ms, "reduced")] == ["d1", "d2"]


def test_metadata_matches_for_stage_unknown_returns_empty() -> None:
    assert metadata_matches_for_stage([_match("d1", 0.95)], "zzz") == []


# --- metadata_filters_from_matches ---


def test_metadata_filters_empty_returns_empty_dict() -> None:
    assert metadata_filters_from_matches([]) == {}


def test_metadata_filters_aggregates_and_dedups() -> None:
    ms = [
        {"doc_id": "d1", "field": "f", "value": "v", "confidence": 0.95, "agency": "A", "project": "P"},
        {"doc_id": "d2", "field": "f", "value": "v", "confidence": 0.75, "agency": "B", "project": "Q"},
        {"doc_id": "d1", "field": "f", "value": "v", "confidence": 0.80, "agency": "A", "project": "P"},
    ]
    out = metadata_filters_from_matches(ms)
    assert out["doc_ids"] == ["d1", "d2"]  # 중복 d1 한 번
    assert out["agencies"] == ["A", "B"]
    assert out["confidence"] == 0.95  # max


# --- best_metadata_doc_scores ---


def test_best_metadata_doc_scores_takes_max_per_doc() -> None:
    ms = [_match("d1", 0.7, value="v"), _match("d1", 0.9, value="v2"), _match("d2", 0.6)]
    assert best_metadata_doc_scores(ms) == {"d1": 0.9, "d2": 0.6}


def test_best_metadata_doc_scores_skips_blank_doc_id() -> None:
    ms = [
        {"doc_id": "", "field": "f", "value": "v", "confidence": 0.9},
        {"doc_id": "d1", "field": "f", "value": "v", "confidence": 0.8},
    ]
    out = best_metadata_doc_scores(ms)
    assert out == {"d1": 0.8}
    assert "" not in out  # 빈 doc_id 는 점수 맵에 들어가지 않는다


# --- metadata_ambiguity_details (5분기) ---


def test_ambiguity_comparison_short_circuits() -> None:
    out = metadata_ambiguity_details([_match("d1", 0.95)], "comparison")
    assert out["ambiguous"] is False
    assert out["reason"] == "comparison_allows_multiple_targets"


def test_ambiguity_no_reduced_candidates() -> None:
    # 0.5 < REDUCED(0.70) → reduced 후보 없음
    out = metadata_ambiguity_details([_match("d1", 0.5)], "single_doc")
    assert out["ambiguous"] is False
    assert out["reason"] == "no_reduced_candidates"


def test_ambiguity_single_candidate() -> None:
    out = metadata_ambiguity_details([_match("d1", 0.95)], "single_doc")
    assert out["ambiguous"] is False
    assert out["reason"] == "single_candidate"
    assert out["candidate_doc_ids"] == ["d1"]


def test_ambiguity_close_scores_flagged() -> None:
    # 0.95 vs 0.94 (델타 0.01 < AMBIGUOUS_CONFIDENCE_DELTA=0.05) → 모호
    ms = [_match("d1", 0.95), _match("d2", 0.94)]
    out = metadata_ambiguity_details(ms, "single_doc")
    assert out["ambiguous"] is True
    assert out["reason"] == "close_candidate_scores"
    assert set(out["candidate_doc_ids"]) == {"d1", "d2"}


def test_ambiguity_clear_top_when_gap_exceeds_delta() -> None:
    # 0.95 vs 0.80 (델타 0.15 > 0.05) → 명확한 1위
    ms = [_match("d1", 0.95), _match("d2", 0.80)]
    out = metadata_ambiguity_details(ms, "single_doc")
    assert out["ambiguous"] is False
    assert out["reason"] == "clear_top_candidate"
    assert out["candidate_doc_ids"] == ["d1"]
