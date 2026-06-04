"""Unit coverage for rag_retrieval.py 유사도 primitive 3종 (issue #2254).

검색 랭킹의 핵심 점수 함수인 유사도 primitive 를 oracle 로 고정한다
(test-only, 소스 무수정).

- ``lexical_similarity`` — token overlap(0.55) + topic substring(0.45) 가중합.
  두 채널 모두 ``[0,1]`` 이라 합의 상한이 정확히 1.0 (``min(1.0, ...)`` 은
  도달 불가능한 방어선). ``chunk.tokens`` 있으면 그것을 우선(미tokenize).
  직접 단위 import 기존 0.
- ``metadata_similarity`` — ``metadata_doc_scores[doc_id]`` 우선, 없으면
  entities↔agency exact match(1.0/0.0). 직접 단위 import 기존 0.
- ``dense_similarity`` — ``(dot+1)/2`` 정규화 + ``[0,1]`` clamp. 기존
  ``test_dense_similarity_shape_validation.py``(issue #784)가 None/parallel/
  anti-parallel(dot=-1)/shape-mismatch 를 이미 커버하므로, 여기서는 그 파일에
  **없는** 신규 정수성만 추가한다 — 정규화 선형성(중간값 orthogonal=0.5)과
  비단위 벡터 양방향 clamp(상한 dot>1 / 하한 dot<-1).

leaf 모듈(rag_text_processing + numpy, rag_core back-edge 0 = ADR 0045; 별도
프로세스 import 에 torch/chromadb/rag_core 0). negative assertion 으로 가중치
비대칭·우선순위·정규화·정수성 가드가 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

import numpy as np
import pytest

from rag_retrieval import dense_similarity, lexical_similarity, metadata_similarity


# --- lexical_similarity ---


def test_lexical_empty_query_and_topics_is_zero() -> None:
    # query_tokens 와 topics 둘 다 비면 early return 0.0
    assert lexical_similarity(set(), [], {"text": "예산 집행 내용", "tokens": ["예산"]}) == 0.0


def test_lexical_overlap_only_is_055() -> None:
    # token overlap 만(topic 없음) → 0.55 가중치
    out = lexical_similarity({"예산"}, [], {"text": "예산", "tokens": ["예산"]})
    assert out == pytest.approx(0.55)


def test_lexical_topic_only_is_045() -> None:
    # topic substring 만(overlap 없음) → 0.45 가중치.
    # tokens=['zzz'] 로 token overlap 을 0 으로 막아 topic 채널만 측정.
    out = lexical_similarity(set(), ["예산"], {"text": "총 예산은 1조", "tokens": ["zzz"]})
    assert out == pytest.approx(0.45)


def test_lexical_overlap_and_topic_weights_are_asymmetric() -> None:
    # 0.55(overlap) ≠ 0.45(topic) — 가중치를 swap 하면 두 값이 뒤바뀌어 KILL.
    overlap_only = lexical_similarity({"예산"}, [], {"text": "예산", "tokens": ["예산"]})
    topic_only = lexical_similarity(set(), ["예산"], {"text": "총 예산은 1조", "tokens": ["zzz"]})
    assert overlap_only > topic_only
    assert overlap_only == pytest.approx(0.55)
    assert topic_only == pytest.approx(0.45)


def test_lexical_both_channels_sum_to_affine_ceiling() -> None:
    # overlap=1 + topic=1 → 0.55+0.45 = 1.0 (두 채널 합의 상한; 둘 다 [0,1])
    out = lexical_similarity({"예산"}, ["예산"], {"text": "예산", "tokens": ["예산"]})
    assert out == pytest.approx(1.0)


def test_lexical_topic_matches_inside_section_path() -> None:
    # section_path 가 chunk_text 에 합쳐져 topic substring 매칭에 기여한다.
    # tokens=['zzz'] 로 overlap 채널을 0 으로 막아 section_path 경로만 측정.
    out = lexical_similarity(set(), ["예산편성"], {"section_path": ["예산편성"], "tokens": ["zzz"]})
    assert out == pytest.approx(0.45)


def test_lexical_prefers_precomputed_tokens_over_text() -> None:
    # chunk.tokens 가 있으면 text 를 tokenize 하지 않고 그것을 쓴다.
    # text 와 무관한 tokens 를 줘서 분기를 못 박는다(text tokenize 였다면 overlap 0).
    out = lexical_similarity({"예산"}, [], {"text": "전혀무관한본문내용", "tokens": ["예산"]})
    assert out == pytest.approx(0.55)


# --- metadata_similarity ---


def test_metadata_doc_scores_hit_returns_float_score() -> None:
    out = metadata_similarity({"metadata_doc_scores": {"d1": 0.7}}, {"doc_id": "d1"})
    assert out == pytest.approx(0.7)


def test_metadata_doc_scores_take_priority_over_entities() -> None:
    # doc_scores 에 doc_id 가 있으면 entities/agency 분기를 건너뛴다.
    # agency 가 entities 에 없어도(→ entities 경로라면 0.0) doc_scores 값 0.3 을 반환.
    out = metadata_similarity(
        {"metadata_doc_scores": {"d1": 0.3}, "entities": ["행안부"]},
        {"doc_id": "d1", "agency": "교육부"},
    )
    assert out == pytest.approx(0.3)


def test_metadata_no_entities_is_zero() -> None:
    assert metadata_similarity({}, {"doc_id": "x", "agency": "행안부"}) == 0.0


def test_metadata_agency_in_entities_is_one() -> None:
    assert metadata_similarity({"entities": ["행안부"]}, {"agency": "행안부"}) == 1.0


def test_metadata_agency_not_in_entities_is_zero() -> None:
    assert metadata_similarity({"entities": ["행안부"]}, {"agency": "교육부"}) == 0.0


# --- dense_similarity ---
# 기존 test_dense_similarity_shape_validation.py(issue #784)가 None/parallel/
# anti-parallel(dot=-1)/shape-mismatch 를 이미 커버한다. 아래는 그 파일에 없는
# 신규 정수성만 추가: 정규화 선형성(중간값)과 비단위 벡터 양방향 clamp.


def test_dense_orthogonal_is_half_not_zero() -> None:
    # dot=0 → (0+1)/2 = 0.5. 정규화가 없으면 0.0 → KILL.
    # parallel/anti-parallel 양 끝점만으로는 (dot+1)/2 선형성이 안 잡혀 중간값으로 못 박는다.
    out = dense_similarity(np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32))
    assert out == pytest.approx(0.5)
    assert out != 0.0


def test_dense_unnormalized_upper_clamps_to_one() -> None:
    # 비단위 벡터 dot=4 → (4+1)/2 = 2.5 → 상한 clamp 1.0
    v = np.array([2.0, 0.0], dtype=np.float32)
    assert dense_similarity(v, v) == pytest.approx(1.0)


def test_dense_unnormalized_lower_clamps_to_zero() -> None:
    # 비단위 anti-parallel dot=-4 → (-4+1)/2 = -1.5 → 하한 clamp 0.0.
    # 기존 anti-parallel 은 dot=-1 → 0.0 이라 하한이 자를 음수가 없어(unreachable)
    # 하한 clamp 제거를 못 잡는다. magnitude-2 로 실제 하한을 검증.
    v = np.array([2.0, 0.0], dtype=np.float32)
    w = np.array([-2.0, 0.0], dtype=np.float32)
    assert dense_similarity(v, w) == pytest.approx(0.0)
