"""Unit coverage for ``scripts/render_verifier_false_negative_overlap.py`` 분류 헬퍼.

verifier false-negative overlap 보드의 슬라이스 집계를 결정하는 순수 버킷·
카디널리티 분류 헬퍼들이다. 경계가 조용히 회귀하면 슬라이스 카운트가 틀어지므로
oracle 로 고정한다. 특히:

- ``_retry_bucket`` 은 ``int()`` coerce 후 버킷팅 — bool 은 int 라 ``True→"1"``,
  비숫자/음수는 ``"0"``, float 은 절삭(``2.9→"2"``).
- ``_expected_coverage``/``_evidence_cardinality`` 는 ``str()`` 정규화 + set 으로
  doc id 를 비교 — falsy 항목은 제외되고 중복은 dedup, ``[1]`` 과 ``["1"]`` 은 교차매치.
- ``_specificity_bucket`` 은 SPECIFICITY_REGEX(얼마|구체적|기준은|몇\\s*%?|\\d+\\s*%) hit.
- ``_p25`` 는 정렬 후 ``min(int(0.25*(n-1)), n-1)`` 인덱스(nearest-rank 변형).

상위 ``build_aggregate``/``render_markdown`` 은 기존 테스트가 end-to-end 로 다루지만
이 헬퍼들의 경계 자체는 미고정이었다. 모든 기대값은 pristine 소스 실행으로 캡처.
``from scripts.render_verifier_false_negative_overlap import ...`` (implicit namespace).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_verifier_false_negative_overlap import (
    _cardinality_bucket,
    _count_list,
    _evidence_cardinality,
    _expected_coverage,
    _p25,
    _retry_bucket,
    _specificity_bucket,
)


# ----------------------------------------------------------------------
# _retry_bucket  (int-coerce 후 0/1/2/3plus; non-int -> 0)
# ----------------------------------------------------------------------

RETRY_BUCKET_CASES = [
    (0, "0"),
    (1, "1"),
    (2, "2"),
    (3, "3plus"),
    (5, "3plus"),
    (-1, "0"),        # 음수 → "0"
    ("2", "2"),       # 정수 문자열 coerce
    ("2.9", "0"),     # float 문자열: int("2.9") 가 ValueError → except → "0" (float 절삭 아님)
    ("x", "0"),       # 비숫자 문자열 → except → 0
    (None, "0"),      # None → TypeError → 0
    (2.9, "2"),       # float 절삭(int(2.9)==2)
    (True, "1"),      # bool 은 int subclass → int(True)==1
    (False, "0"),
]


@pytest.mark.parametrize("value, expected", RETRY_BUCKET_CASES)
def test_retry_bucket(value: Any, expected: str) -> None:
    assert _retry_bucket(value) == expected


# ----------------------------------------------------------------------
# _cardinality_bucket  (int 직접 0/1/2/3plus)
# ----------------------------------------------------------------------

CARDINALITY_BUCKET_CASES = [
    (-1, "0"),
    (0, "0"),
    (1, "1"),
    (2, "2"),
    (3, "3plus"),
    (9, "3plus"),
]


@pytest.mark.parametrize("count, expected", CARDINALITY_BUCKET_CASES)
def test_cardinality_bucket(count: int, expected: str) -> None:
    assert _cardinality_bucket(count) == expected


# ----------------------------------------------------------------------
# _expected_coverage  (str 정규화 set 교차)
# ----------------------------------------------------------------------

EXPECTED_COVERAGE_CASES = [
    ({}, "no_expected"),
    ({"expected_doc_ids": []}, "no_expected"),
    ({"expected_doc_ids": ["a"], "evidence_doc_ids": ["a", "b"]}, "expected_in_evidence"),
    ({"expected_doc_ids": ["a"], "evidence_doc_ids": ["b"]}, "expected_not_in_evidence"),
    # falsy 항목(None, "") 제외 후에도 expected 가 남으면 not_in_evidence
    ({"expected_doc_ids": ["a", None, ""], "evidence_doc_ids": []}, "expected_not_in_evidence"),
    # expected 가 전부 falsy → 필터 후 빈 set → no_expected (not_in_evidence 아님)
    ({"expected_doc_ids": [None, ""], "evidence_doc_ids": ["x"]}, "no_expected"),
    # str() 정규화로 1 과 "1" 이 교차매치
    ({"expected_doc_ids": [1], "evidence_doc_ids": ["1"]}, "expected_in_evidence"),
]


@pytest.mark.parametrize("case, expected", EXPECTED_COVERAGE_CASES)
def test_expected_coverage(case: dict[str, Any], expected: str) -> None:
    assert _expected_coverage(case) == expected


# ----------------------------------------------------------------------
# _evidence_cardinality  (set dedup; falsy 제외)
# ----------------------------------------------------------------------

EVIDENCE_CARDINALITY_CASES = [
    ({}, "empty"),
    ({"evidence_doc_ids": ["a"]}, "single_doc"),
    ({"evidence_doc_ids": ["a", "b"]}, "multi_doc"),
    ({"evidence_doc_ids": ["a", "a"]}, "single_doc"),   # 중복 dedup → 1
    ({"evidence_doc_ids": [None, ""]}, "empty"),         # falsy 전부 제외 → empty
]


@pytest.mark.parametrize("case, expected", EVIDENCE_CARDINALITY_CASES)
def test_evidence_cardinality(case: dict[str, Any], expected: str) -> None:
    assert _evidence_cardinality(case) == expected


# ----------------------------------------------------------------------
# _specificity_bucket  (SPECIFICITY_REGEX hit)
# ----------------------------------------------------------------------

SPECIFICITY_HIT = ["얼마인가요", "구체적 기준", "기준은 무엇", "몇 개입니까", "30%", "3 %", "수수료 50 % 인가"]
SPECIFICITY_MISS = ["", "2024년 별표 5", "일반 질문"]


@pytest.mark.parametrize("query", SPECIFICITY_HIT)
def test_specificity_bucket_hit(query: str) -> None:
    assert _specificity_bucket({"query": query}) == "keyword_hit"


@pytest.mark.parametrize("query", SPECIFICITY_MISS)
def test_specificity_bucket_miss(query: str) -> None:
    assert _specificity_bucket({"query": query}) == "no_hit"


@pytest.mark.parametrize("case", [{}, {"query": None}, {"query": 123}])
def test_specificity_bucket_non_string_query_no_hit(case: dict[str, Any]) -> None:
    # query 누락/None/비문자열 → str(... or "")="" 또는 숫자 문자열 → 매치 없음.
    assert _specificity_bucket(case) == "no_hit"


# ----------------------------------------------------------------------
# _p25  (정렬 후 min(int(0.25*(n-1)), n-1) 인덱스)
# ----------------------------------------------------------------------

P25_CASES = [
    ([], None),
    ([5.0], 5.0),
    ([1.0, 2.0, 3.0, 4.0], 1.0),       # n=4 → idx=int(0.75)=0 → 정렬[0]=1.0
    ([4.0, 1.0, 3.0, 2.0], 1.0),       # 정렬 후 동일
    ([1.0, 2.0, 3.0, 4.0, 5.0], 2.0),  # n=5 → idx=int(1.0)=1 → 정렬[1]=2.0
]


@pytest.mark.parametrize("values, expected", P25_CASES)
def test_p25(values: list[float], expected: float | None) -> None:
    assert _p25(values) == expected


# ----------------------------------------------------------------------
# _count_list  (list 면 len, 아니면 0)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ([1, 2], 2),
        ([], 0),
        ("ab", 0),       # str 은 list 아님 → 0(문자 길이 아님)
        (None, 0),
        ({"a": 1}, 0),
        ((1, 2), 0),     # tuple 은 list 아님 → 0
    ],
)
def test_count_list(value: Any, expected: int) -> None:
    assert _count_list(value) == expected
