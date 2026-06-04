"""Unit coverage for rag_retrieval.bm25_scores_for_index (issue #2271).

``bm25_scores_for_index`` 는 hybrid 검색의 BM25 채널(ADR 0058)이다. 기존
테스트는 RRF/hybrid 통합·``bm25_extra`` 필터·kiwi 토크나이저만 다뤄, 함수
자체의 빈 query all-zero·매칭/비매칭 score map·chunk_id 키 보존·query-term
반영은 미커버였다 (test-only, 소스 무수정).

regex tokenizer + okapi backend 는 결정적. BM25 score 절대값은 rank_bm25
버전 의존이라 구조 속성(early-return 동등성·대칭·매칭/비매칭 부등식·키 보존)
으로 못 박는다. 캐시 side-effect(``_bm25*`` 키를 index 에 mutate)를 피하려
각 테스트는 fresh index literal 을 쓴다.

leaf 모듈(rank_bm25 + rag_text_processing, rag_core back-edge 0 = ADR 0045).
``bm25_extra``/kiwi 분기는 기존 테스트 중복이라 제외.
"""
from __future__ import annotations

from typing import Any

from rag_retrieval import bm25_scores_for_index


def _index() -> dict[str, Any]:
    # c1·c3 둘 다 "예산" 정확히 1개 + 길이 3 → 동일 분포(대칭). c2 는 "예산" 없음.
    return {
        "chunks": [
            {"chunk_id": "c1", "tokens": ["예산", "집행", "내역"]},
            {"chunk_id": "c2", "tokens": ["계약", "조건", "검토"]},
            {"chunk_id": "c3", "tokens": ["예산", "편성", "계획"]},
        ]
    }


def test_empty_query_yields_all_zero_map() -> None:
    # 빈 query_tokens → early return: 모든 chunk_id 가 0.0
    idx = _index()
    out = bm25_scores_for_index(idx, [])
    assert out == {"c1": 0.0, "c2": 0.0, "c3": 0.0}
    # early-return 은 값뿐 아니라 메커니즘도 pin: BM25 코퍼스를 빌드하지 않는다.
    # guard 를 제거하면 get_or_build_bm25 가 호출돼 _bm25* 캐시 키가 index 에
    # mutate 되므로 → KILL (정상 query 는 이 키들을 만든다, 아래 대조).
    assert not any(k.startswith("_bm25") for k in idx)


def test_empty_chunks_yields_empty_map() -> None:
    assert bm25_scores_for_index({"chunks": []}, ["예산"]) == {}


def test_missing_chunks_key_yields_empty_map() -> None:
    # index 에 chunks 키가 없으면 (index.get("chunks") or []) → {}
    assert bm25_scores_for_index({}, ["예산"]) == {}


def test_matching_chunks_are_symmetric_and_distinct() -> None:
    # "예산" 은 c1·c3 에 동일 분포로 존재 → 같은 score(대칭). 매칭 score 는
    # 비매칭(c2=0.0)과 구별된다. 절대 부호(>0)는 rank_bm25 epsilon-floor 에
    # 의존해 fragile 하므로(라이브러리 업그레이드 시 깨질 수 있음), 부호 무관한
    # 대칭 + 매칭≠비매칭으로 고정한다. "매칭>비매칭" 방향 계약은 T5 가 담당.
    out = bm25_scores_for_index(_index(), ["예산"])
    assert out["c1"] == out["c3"]  # 대칭: 상수 mutant 가 아닌 실제 동일 분포 반영
    assert out["c1"] != out["c2"]  # 매칭은 비매칭과 구별(부호 가정 없음)


def test_non_matching_chunk_is_zero_and_below_match() -> None:
    # "예산" 을 포함하지 않는 c2 는 0.0, 매칭 chunk 보다 작다.
    out = bm25_scores_for_index(_index(), ["예산"])
    assert out["c2"] == 0.0
    assert out["c1"] > out["c2"]


def test_keys_preserve_all_chunk_ids() -> None:
    out = bm25_scores_for_index(_index(), ["예산"])
    assert set(out.keys()) == {"c1", "c2", "c3"}


def test_added_query_term_lifts_previously_zero_chunk() -> None:
    # 단일 "예산" 에서 c2(계약)는 0.0 이었는데, query 에 "계약" 을 더하면 c2 > 0.
    # query token 이 실제로 score 에 반영됨을 못 박는다(query 무시 mutant KILL).
    single = bm25_scores_for_index(_index(), ["예산"])
    multi = bm25_scores_for_index(_index(), ["예산", "계약"])
    assert single["c2"] == 0.0
    assert multi["c2"] > 0.0
