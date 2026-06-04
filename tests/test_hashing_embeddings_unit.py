"""Unit coverage for rag_embedding.hashing_embeddings (issue #2262).

``hashing_embeddings(texts, dim)`` 는 ADR 0001 오프라인 baseline 의 핵심 결정적
임베딩(md5 해싱 → signed feature → 행별 L2 정규화)이다. 기존 테스트는
``embed_query_for_index`` 단일 쿼리 shape 와 openai 백엔드 정규화만 다뤄
``hashing_embeddings`` 자체의 다중 텍스트 shape·결정성·행별 L2 정규화·
zero-vector 가드·dtype 은 미커버였다 (test-only, 소스 무수정).

negative assertion 으로 baseline byte-identical 불변(ADR 0001)을 떠받치는
속성들이 실제로 성립하는지 못 박는다. leaf 모듈(hashlib/numpy +
rag_text_processing.tokenize, rag_core back-edge 0 = ADR 0045).

- ``expand_features`` 는 issue #2105 로 이미 완전 단위 커버 → 여기서 제외(중복 회피).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from rag_embedding import hashing_embeddings


def test_shape_is_rows_by_dim() -> None:
    # (len(texts), dim) — 행/열 순서를 못 박는다(전치면 (dim, len)이 되어 KILL)
    v = hashing_embeddings(["가나", "다라", "마바"], 16)
    assert v.shape == (3, 16)


def test_dtype_is_float32() -> None:
    v = hashing_embeddings(["예산"], 8)
    assert v.dtype == np.float32


def test_dim_argument_controls_columns() -> None:
    assert hashing_embeddings(["예산 집행"], 64).shape[1] == 64
    assert hashing_embeddings(["예산 집행"], 16).shape[1] == 16


def test_nonzero_rows_are_l2_normalized() -> None:
    # 토큰이 있는 행은 단위 L2 norm. 정규화(vectors/norms)를 제거하면 raw signed
    # count 가 남아 norm != 1.0 → KILL.
    v = hashing_embeddings(["예산 집행 내용 상세"], 32)
    assert float(np.linalg.norm(v[0])) == pytest.approx(1.0)


def test_deterministic_for_same_input() -> None:
    # md5 기반이라 재호출이 byte-identical. 비결정(random) 구현이면 KILL.
    a = hashing_embeddings(["예산 집행 내용"], 32)
    b = hashing_embeddings(["예산 집행 내용"], 32)
    assert np.array_equal(a, b)


def test_distinct_texts_produce_distinct_vectors() -> None:
    # 서로 다른 텍스트는 다른 벡터(상수/zero 반환 mutant 면 동일해져 KILL)
    a = hashing_embeddings(["예산"], 32)
    b = hashing_embeddings(["계약"], 32)
    assert not np.array_equal(a, b)


def test_negative_sign_token_is_preserved() -> None:
    # signed-feature 속성: digest[8:10] 홀수면 sign=-1. "기한" 은 단일 토큰이고
    # 부호 비트가 홀수라 정규화 후 유일 비-zero 성분 = -1.0. sign 분기를 항상
    # +1.0 으로 바꾸면 그 성분이 +1.0 이 되어 min()=0.0 → KILL (부호를 못 박음).
    assert float(hashing_embeddings(["기한"], 8).min()) == pytest.approx(-1.0)


def test_same_index_collisions_accumulate() -> None:
    # "예산 예산": 동일 unigram 2개가 같은 idx 로 충돌 → '+=' 누적으로 magnitude 2,
    # bigram '예산_예산' 은 다른 idx 로 magnitude 1. 정규화 후 두 성분 비율 정확히
    # 2.0. 누적을 대입('=')으로 바꾸면 unigram 도 magnitude 1 → 비율 1.0 → KILL.
    v = hashing_embeddings(["예산 예산"], 32)[0]
    nz = np.sort(np.abs(v[v != 0]))
    assert len(nz) == 2
    assert nz[1] == pytest.approx(2.0 * nz[0])


def test_empty_text_is_zero_vector_without_nan() -> None:
    # 토큰 없는 빈 텍스트 → 행 전체 0. norms[norms==0]=1.0 가드가 0/0 nan 을
    # 막는다. 가드를 제거하면 nan 이 되어 all-zero(==0) 도 no-nan 도 위반 → KILL.
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # 0/0 invalid-divide 경고를 에러로 격상
        v = hashing_embeddings([""], 8)
    assert bool(np.all(v[0] == 0.0))
    assert not bool(np.any(np.isnan(v[0])))


def test_mixed_empty_and_nonempty_rows_independent() -> None:
    # 빈 행(norm 0)과 정상 행(norm 1)이 한 배치에서 독립적으로 정규화된다
    v = hashing_embeddings(["", "예산 집행"], 16)
    assert float(np.linalg.norm(v[0])) == 0.0
    assert float(np.linalg.norm(v[1])) == pytest.approx(1.0)
