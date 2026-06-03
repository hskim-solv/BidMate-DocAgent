"""Unit coverage for rag_metadata_processing.py entity matching (issue #2190).

#2177 follow-up — rag_metadata_processing.py 의 마지막 미커버 함수군(metadata
entity 매칭 3종)을 커버해 모듈 단위 커버리지를 완성한다 (정규화 #2168 ·
후처리 #2173 · target 구성 #2177 에 이은 4번째, test-only, 소스 무수정):

- ``match_metadata_targets`` — query→targets 매칭 오케스트레이션(compact/tokens
  계산 + 전략 적용 + dedupe)
- ``match_metadata_target`` — 6단계 매칭 전략(compact_contains 1.0 / explicit_alias
  0.92 / abbreviation 0.78 / partial_tokens 0.70~0.89 / fuzzy ≤0.84 / None)
- ``best_metadata_phrase_similarity`` — difflib SequenceMatcher 기반 phrase 유사도

전부 결정적(난수 없음). 고정 confidence 상수(1.0/0.92/0.78)는 정확값으로,
ratio 의존 partial_tokens 는 경계 범위로 단언해 견고하게 둔다. leaf 모듈
(rag_text_processing/rag_conversation_state/korean_lexicon + stdlib, ADR 0045 보존).
"""
from __future__ import annotations

from typing import Any

import pytest

from rag_metadata_processing import (
    best_metadata_phrase_similarity,
    compact_metadata_text,
    make_metadata_target,
    match_metadata_target,
    match_metadata_targets,
    metadata_tokens,
)


def _target(field: str, value: str, doc_id: str = "d1", **metadata: Any) -> dict[str, Any]:
    doc = {
        "doc_id": doc_id,
        "agency": value if field == "agency" else "",
        "project": value if field == "project" else "",
        "metadata": metadata,
    }
    return make_metadata_target(doc, field, value)


# --- best_metadata_phrase_similarity ---


def test_phrase_similarity_identical_is_one() -> None:
    assert best_metadata_phrase_similarity(["행정", "안전부"], ["행정", "안전부"]) == 1.0


def test_phrase_similarity_empty_is_zero() -> None:
    # 한쪽이라도 비면 0.0 (difflib 호출 전 early return)
    assert best_metadata_phrase_similarity([], ["x"]) == 0.0
    assert best_metadata_phrase_similarity(["x"], []) == 0.0


def test_phrase_similarity_unrelated_is_low() -> None:
    score = best_metadata_phrase_similarity(["행정안전부"], ["교육부"])
    assert 0.0 < score < 0.5  # 무관 토큰은 낮은 유사도


# --- match_metadata_targets: 전략별 confidence/match_type ---


def test_match_compact_contains_full_confidence() -> None:
    # target compact 가 query compact 에 포함 → 최고 신뢰 1.0
    matches = match_metadata_targets("행정안전부 예산 알려줘", [_target("agency", "행정안전부")])
    assert len(matches) == 1
    assert matches[0]["match_type"] == "compact_contains"
    assert matches[0]["confidence"] == 1.0


def test_match_explicit_alias_confidence() -> None:
    # metadata.agency_aliases 의 별칭이 query 에 등장 → explicit_alias 0.92
    target = _target("agency", "행정안전부", agency_aliases="행안부")
    matches = match_metadata_targets("행안부 예산은?", [target])
    assert matches[0]["match_type"] == "explicit_alias"
    assert matches[0]["confidence"] == 0.92
    assert "행안부" in matches[0]["matched_terms"]


def test_match_abbreviation_confidence() -> None:
    # agency 영숫자 alias('mois')가 query token 으로 등장 → abbreviation 0.78
    matches = match_metadata_targets("mois 예산", [_target("agency", "MOIS청")])
    assert matches[0]["match_type"] == "abbreviation"
    assert matches[0]["confidence"] == 0.78


def test_match_partial_tokens_two_overlap_confidence() -> None:
    # core token 2개 겹침 → partial_tokens. conf = min(0.89, 0.70 + 0.19*ratio),
    # ratio=2/3 → 0.827. approx 로 cap·공식 양쪽 mutation 을 포착하면서 무리수 흡수
    matches = match_metadata_targets("정보화 사업 추진", [_target("project", "정보화 추진 계획")])
    assert matches[0]["match_type"] == "partial_tokens"
    assert matches[0]["confidence"] == pytest.approx(0.827, abs=0.01)


def test_match_partial_tokens_single_overlap_special_case() -> None:
    # project/title 이고 core_tokens<=2, 단일 overlap 이 3자 이상이면 0.72 partial_tokens
    # ('정보화 시스템' → '시스템'은 generic 제외 → core=['정보화'], query 와 1개 겹침)
    matches = match_metadata_targets("정보화 관련 질문", [_target("project", "정보화 시스템")])
    assert matches[0]["match_type"] == "partial_tokens"
    assert matches[0]["confidence"] == 0.72
    assert matches[0]["matched_terms"] == ["정보화"]


def test_match_fuzzy_similarity_fallback() -> None:
    # overlap<2 라 partial 미달이지만 phrase 유사도가 높으면 fuzzy_similarity (conf<=0.84)
    matches = match_metadata_targets("행정안전 관련 자료", [_target("agency", "행정안전부")])
    assert matches[0]["match_type"] == "fuzzy_similarity"
    assert matches[0]["confidence"] == 0.84


def test_match_unrelated_query_returns_no_matches() -> None:
    matches = match_metadata_targets("전혀 무관한 질문입니다", [_target("agency", "행정안전부")])
    assert matches == []


def test_match_dedupes_same_doc_to_best() -> None:
    # 같은 doc 이 여러 전략에 걸려도 최고 confidence 하나만 남는다
    target = _target("agency", "행정안전부", agency_aliases="행안부")
    matches = match_metadata_targets("행정안전부 행안부", [target])
    assert len(matches) == 1
    assert matches[0]["confidence"] == 1.0  # compact_contains 가 explicit_alias 를 이긴다


# --- match_metadata_target: 저수준 직접 호출 ---


def test_match_metadata_target_low_level_hit_and_miss() -> None:
    target = _target("agency", "교육부", doc_id="d2")
    # hit: query compact 에 target compact 포함
    qc, qt = compact_metadata_text("교육부 사업"), metadata_tokens("교육부 사업")
    hit = match_metadata_target(qc, qt, set(qt), target)
    assert hit is not None
    assert hit["match_type"] == "compact_contains"
    # miss: 무관 query → None
    miss_tokens = metadata_tokens("날씨 정보")
    miss = match_metadata_target(
        compact_metadata_text("날씨 정보"), miss_tokens, set(miss_tokens), target
    )
    assert miss is None
