"""Unit coverage for ``scripts/render_difficulty_profile.py`` 버킷팅 헬퍼.

eval 케이스 난이도 프로파일 렌더러의 순수 분류/정규화 헬퍼들이다. 버킷 경계가
조용히 밀리면 난이도 분포 집계가 틀어지므로, 임계값(0/1/3/4)·missing 경로·
strip/dedup 동작을 oracle 로 고정한다.

``scripts/`` 는 repo 루트에서 도달 가능한 implicit namespace package 라
``from scripts.render_difficulty_profile import ...`` 로 import 한다.
모든 기대값은 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_difficulty_profile import (
    _bucket_count,
    _expected_terms_bucket,
    _gold_chunk_bucket,
    _gold_doc_bucket,
    _unique_strings,
)


# ----------------------------------------------------------------------
# _unique_strings
# ----------------------------------------------------------------------


def test_unique_strings_strips_dedups_and_drops_falsy_preserving_order() -> None:
    assert _unique_strings(["a", " a ", "", "b", None, "a", "  c  "]) == ["a", "b", "c"]


@pytest.mark.parametrize("value", [None, "abc", 5, {"a": 1}])
def test_unique_strings_non_list_returns_empty(value: Any) -> None:
    assert _unique_strings(value) == []


def test_unique_strings_empty_list_returns_empty() -> None:
    assert _unique_strings([]) == []


# ----------------------------------------------------------------------
# _bucket_count  (경계 0 / 1 / 3 / 4)
# ----------------------------------------------------------------------

BUCKET_CASES = [
    (None, "missing"),
    (-1, "0"),    # ≤0
    (0, "0"),
    (1, "1"),
    (2, "2_3"),
    (3, "2_3"),   # ≤3 상한
    (4, "4_plus"),  # 4 부터 4_plus
    (100, "4_plus"),
]


@pytest.mark.parametrize("count, expected", BUCKET_CASES)
def test_bucket_count_boundaries(count: int | None, expected: str) -> None:
    assert _bucket_count(count) == expected


def test_bucket_count_custom_missing_label() -> None:
    assert _bucket_count(None, missing_label="N/A") == "N/A"
    # missing_label 은 None 일 때만 쓰인다 — 숫자 경로엔 영향 없음.
    assert _bucket_count(0, missing_label="N/A") == "0"


# ----------------------------------------------------------------------
# _expected_terms_bucket
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        {},                              # 키 없음
        {"expected_terms": None},        # None
        {"expected_terms": "x"},         # non-list
    ],
)
def test_expected_terms_bucket_missing_paths(case: dict) -> None:
    assert _expected_terms_bucket(case) == "missing"


def test_expected_terms_bucket_counts_nonblank_terms() -> None:
    assert _expected_terms_bucket({"expected_terms": []}) == "0"
    # 공백/빈 문자열 term 은 개수에서 제외된다.
    assert _expected_terms_bucket({"expected_terms": ["a", "", "  "]}) == "1"
    assert _expected_terms_bucket({"expected_terms": ["a", "b", "c"]}) == "2_3"
    assert _expected_terms_bucket({"expected_terms": ["a", "b", "c", "d"]}) == "4_plus"


def test_expected_terms_bucket_counts_falsy_nonstring_terms() -> None:
    # 의도된 divergence: 필터가 `str(term).strip()`(not `str(term or "")`)이라
    # None/0/False 도 'None'/'0'/'False' 로 stringify 되어 non-blank 으로 카운트된다
    # (_unique_strings 의 falsy-drop 과 다름). 이 동작을 회귀로부터 고정한다.
    assert _expected_terms_bucket({"expected_terms": ["a", None, 0]}) == "2_3"


# ----------------------------------------------------------------------
# _gold_doc_bucket / _gold_chunk_bucket
# ----------------------------------------------------------------------

GOLD_DOC_CASES = [
    (1, "single_doc"),
    (2, "multi_doc"),
    (5, "multi_doc"),
    (0, "unknown"),
    (None, "unknown"),
    (-1, "unknown"),
]


@pytest.mark.parametrize("count, expected", GOLD_DOC_CASES)
def test_gold_doc_bucket(count: int | None, expected: str) -> None:
    assert _gold_doc_bucket(count) == expected


GOLD_CHUNK_CASES = [
    (0, "none"),
    (1, "single_chunk"),
    (2, "multi_chunk"),
    (5, "multi_chunk"),
    (-1, "multi_chunk"),  # 음수는 0/1 어느 분기도 아님 → else(multi_chunk); `==0`→`<=0` 회귀 가드
]


@pytest.mark.parametrize("count, expected", GOLD_CHUNK_CASES)
def test_gold_chunk_bucket(count: int, expected: str) -> None:
    assert _gold_chunk_bucket(count) == expected
