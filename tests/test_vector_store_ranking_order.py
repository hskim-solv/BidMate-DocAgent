"""Unit coverage for rag_vector_store.py ranking-determinism 정렬 helper (issue #2321).

``_sort_pairs_by_score_then_id`` / ``_top_k_order_from_scores`` 는 검색 결과 순서의
결정성(determinism)을 책임지는 import-safe leaf(numpy 외 torch/chromadb/rag_core
미로드)인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``_sort_pairs_by_score_then_id`` — score 내림차순, 동률이면 id **오름차순** tie-break.
  id 를 내림차순으로 뒤집거나 score 를 오름차순으로 바꾸면 KILL.
- ``_top_k_order_from_scores`` — full-sort 경로(k==len)의 동률 인덱스는 stable(인덱스
  오름차순) 유지; 길이 17 all-equal 입력으로 ``kind="stable"`` 제거를 KILL(numpy
  introsort 는 insertion-sort cutoff 16 초과에서 stability 가 깨진다). partition
  경로(k<len)의 동률 순서는 argpartition 구현에 의존하며 인덱스 오름차순을 일반
  보장하지 않는다(작은 입력에서 관찰되는 순서만 결정적으로 고정). top_k>len 은 clamp.
"""
from __future__ import annotations

import numpy as np

from rag_vector_store import _sort_pairs_by_score_then_id, _top_k_order_from_scores


# ---- _sort_pairs_by_score_then_id ----

def test_sort_pairs_score_desc_with_id_asc_tiebreak() -> None:
    out = _sort_pairs_by_score_then_id([(1, 0.5), (2, 0.9), (3, 0.5)])
    assert out == [(2, 0.9), (1, 0.5), (3, 0.5)]
    # 최고 score 가 맨 앞(내림차순). score asc 로 뒤집으면 KILL.
    assert out[0] == (2, 0.9)
    # 동률 0.5 는 id 1 < 3 순서 — id desc tie-break 이면 KILL.
    assert out[1][0] < out[2][0]


def test_sort_pairs_all_equal_scores_order_by_id() -> None:
    # 전부 동률이면 순수 id 오름차순.
    assert _sort_pairs_by_score_then_id([(3, 0.5), (1, 0.5), (2, 0.5)]) == [
        (1, 0.5),
        (2, 0.5),
        (3, 0.5),
    ]


def test_sort_pairs_empty_and_single() -> None:
    assert _sort_pairs_by_score_then_id([]) == []
    assert _sort_pairs_by_score_then_id([(7, 0.1)]) == [(7, 0.1)]


# ---- _top_k_order_from_scores ----

def test_top_k_partition_path_deterministic_order() -> None:
    # partition 경로(k<len): 0.9 가 인덱스 1·3 동률 → 이 입력에서 결정적으로 [1, 3].
    # (argpartition 이 이 작은 입력에선 동률을 오름차순으로 남긴다 — 일반적인 stable
    #  보장은 full-sort 경로의 test_top_k_full_sort_stability_pinned_len17 이 담당.)
    out = _top_k_order_from_scores(np.array([0.1, 0.9, 0.5, 0.9]), 2).tolist()
    assert out == [1, 3]
    assert out[0] < out[1]


def test_top_k_full_sort_stability_pinned_len17() -> None:
    # full-sort 경로(k==len) stable 의 진짜 discriminator: 길이 17 all-equal 은 numpy
    # introsort 의 insertion-sort cutoff(16)를 넘겨 stable 과 quicksort 결과가 갈린다.
    # kind="stable" 이면 인덱스 오름차순 유지; 제거하면 순서가 흔들려 KILL.
    assert _top_k_order_from_scores(np.zeros(17), 17).tolist() == list(range(17))


def test_top_k_full_sort_when_k_equals_len() -> None:
    # k==len 은 full argsort(-scores) 경로: 0.9>0.5>0.1 → [1, 2, 0].
    assert _top_k_order_from_scores(np.array([0.1, 0.9, 0.5]), 3).tolist() == [1, 2, 0]


def test_top_k_clamps_when_k_exceeds_len() -> None:
    # top_k=5 > len=2 → 2개만, 높은 score 먼저: 0.7(idx1) > 0.3(idx0) → [1, 0].
    assert _top_k_order_from_scores(np.array([0.3, 0.7]), 5).tolist() == [1, 0]


def test_top_k_single_and_all_equal_small_input() -> None:
    # k=1 은 최고 score(동률이면 가장 작은 인덱스) 하나.
    assert _top_k_order_from_scores(np.array([0.1, 0.9, 0.5, 0.9]), 1).tolist() == [1]
    # 작은 all-equal 입력은 결정적으로 [0, 1](일반 stable 보장은 len17 테스트가 담당).
    assert _top_k_order_from_scores(np.array([0.5, 0.5, 0.5]), 2).tolist() == [0, 1]
