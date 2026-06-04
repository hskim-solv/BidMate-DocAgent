"""Unit coverage for rag_tracing.py 통계 유틸 + evidence 정제 헬퍼 (issue #2198).

``rag_tracing.py`` (446 LOC, 8 공개함수) 중 기존 테스트는 ``build_result_trace`` /
``redact_trace`` 만 커버한다. 이 파일은 trace 구성과 독립적인 순수 헬퍼 3종의
동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정). summarize_stage_attempt/
build_query_rewrite_trace/build_planner_trace 같은 trace 구성 함수는 별도 concern
→ follow-up.

- ``percentile`` — 정렬 + 선형 보간(빈→None, 단일→값, lower==upper 정확 인덱스,
  그 외 lower/upper 가중평균)
- ``rate`` — 산술 평균(빈→None)
- ``strip_internal_scores`` — evidence 를 public 필드 whitelist 로 정제. internal
  점수(rerank_score/bm25_score 등)를 떨어뜨리고 regions/page_span 만 정규화 →
  ADR 0005 evidence 공개 경계 가드

leaf 모듈(rag_metadata_processing + stdlib math/copy/time, rag_core back-edge 0 =
ADR 0045 보존). negative assertion 으로 보간 분기/평균/internal-key drop 이 실제로
일어나는지 못 박는다(정확-인덱스 fallback·sum·passthrough mutant 를 KILL).
"""
from __future__ import annotations

from typing import Any

from rag_tracing import percentile, rate, strip_internal_scores


# --- percentile ---


def test_percentile_empty_is_none() -> None:
    # 빈 입력은 0.0 이 아니라 None(미정의) — abstention-friendly
    assert percentile([], 0.5) is None


def test_percentile_single_value() -> None:
    assert percentile([42.0], 0.9) == 42.0


def test_percentile_interpolates_between_neighbours() -> None:
    # [10,20,30,40], pct=0.5 → rank=1.5 → 20*0.5 + 30*0.5 = 25.0
    # 정확-인덱스 fallback(ordered[int(1.5)]=20)이면 25.0 이 안 나옴 → 보간 분기 KILL
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0


def test_percentile_weight_is_proportional() -> None:
    # [0,10], pct=0.25 → rank=0.25 → 0*0.75 + 10*0.25 = 2.5
    assert percentile([0.0, 10.0], 0.25) == 2.5


def test_percentile_boundaries_hit_exact_ends() -> None:
    assert percentile([10.0, 20.0], 0.0) == 10.0
    assert percentile([10.0, 20.0], 1.0) == 20.0


def test_percentile_exact_index_no_interpolation() -> None:
    # [10,20,30], pct=0.5 → rank=1.0 → lower==upper → ordered[1]=20.0 (보간 없음)
    assert percentile([10.0, 20.0, 30.0], 0.5) == 20.0


def test_percentile_sorts_input_first() -> None:
    # 미정렬 입력도 정렬 후 계산 — 순서 보존 mutant 면 결과가 달라짐
    assert percentile([30.0, 10.0, 20.0], 0.5) == 20.0


# --- rate ---


def test_rate_is_arithmetic_mean() -> None:
    # mean=0.5. sum(=1.5) mutant 면 KILL
    assert rate([0.0, 1.0, 0.5]) == 0.5


def test_rate_empty_is_none() -> None:
    assert rate([]) is None


def test_rate_single_value() -> None:
    assert rate([0.8]) == 0.8


# --- strip_internal_scores ---


def _evidence_item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "doc_id": "d1",
        "chunk_id": "c1",
        "title": "표제",
        "text": "본문",
        "score": 0.9,
    }
    base.update(overrides)
    return base


def test_strip_internal_scores_drops_internal_score_fields() -> None:
    item = _evidence_item(
        agency="행안부",
        rerank_score=0.71,
        bm25_score=3.2,
        dense_score=0.55,
        _internal="secret",
    )
    out = strip_internal_scores([item])
    assert len(out) == 1
    public = out[0]
    # whitelist 정제: 명시 안 한 internal 점수는 전부 제거(passthrough mutant KILL)
    assert "rerank_score" not in public
    assert "bm25_score" not in public
    assert "dense_score" not in public
    assert "_internal" not in public
    # public 필드는 보존
    assert public["doc_id"] == "d1"
    assert public["score"] == 0.9
    assert public["agency"] == "행안부"


def test_strip_internal_scores_fills_get_defaults() -> None:
    # 선택 필드 누락 시 .get 기본값으로 채워진다(키는 항상 존재)
    out = strip_internal_scores([_evidence_item()])
    public = out[0]
    assert public["agency"] == ""
    assert public["metadata"] == {}
    assert public["section_id"] is None  # 누락 시 None(빈 문자열 아님)
    assert public["retrieval_mode"] == "flat"  # 유일하게 비-falsy 기본값
    assert public["child_chunk_ids"] == []


def test_strip_internal_scores_normalizes_and_adds_regions_page_span() -> None:
    # regions 에 잉여 internal 키를 섞는다 → normalize_regions 호출을 거쳐야만
    # 떨어진다. strip 이 normalize 를 우회(raw passthrough)하면 INTERNAL_LEAK 가
    # 살아남아 아래 두 단언이 KILL → 정규화 wiring 자체를 못 박는다(ADR 0005).
    item = _evidence_item(
        regions=[{"page_number": 2, "bbox": [1, 2, 3, 4], "INTERNAL_LEAK": "secret-coords"}],
        page_span=[2, 2],
    )
    public = strip_internal_scores([item])[0]
    assert public["regions"] == [{"page_number": 2, "bbox": [1, 2, 3, 4]}]
    assert "INTERNAL_LEAK" not in public["regions"][0]
    assert public["page_span"] == [2, 2]


def test_strip_internal_scores_omits_falsy_regions_and_page_span() -> None:
    # regions/page_span 가 비면 키 자체를 추가하지 않는다(조건부 add)
    public = strip_internal_scores([_evidence_item()])[0]
    assert "regions" not in public
    assert "page_span" not in public


def test_strip_internal_scores_empty_evidence_returns_empty_list() -> None:
    assert strip_internal_scores([]) == []
