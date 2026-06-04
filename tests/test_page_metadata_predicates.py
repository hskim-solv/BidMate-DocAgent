"""Unit coverage for ``scripts/page_metadata_recovery_audit.py`` 구조 술어 헬퍼.

페이지 메타데이터 복구 감사가 항목을 분류할 때 쓰는 순수 술어들이다. 경계가
조용히 회귀하면 감사 집계(coverage_block)가 틀어지므로 oracle 로 고정한다. 특히:

- ``bool`` 은 ``int`` 의 subclass 라 ``[True, False]`` 가 page_span 으로,
  ``page_number=True`` 가 region page 로 **통과**한다(의도된 동작, 핀으로 고정).
- ``_is_bbox`` 는 ``float()`` coercion 을 쓰므로 ``"1.0"`` 같은 숫자 문자열도 허용.
- ``_regions`` 는 ``list`` 가 아니면 ``[]`` — tuple 도 제외된다(문자/엔트리 오판 방지).
- ``_has_page_metadata`` 는 ``page_span`` 유효 **또는** region page 존재의 OR.

모든 기대값은 pristine 소스 실행으로 캡처했다.
``from scripts.page_metadata_recovery_audit import ...`` (implicit namespace).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.page_metadata_recovery_audit import (
    _has_page_metadata,
    _has_region_bbox,
    _has_region_page,
    _is_bbox,
    _is_page_span,
    _regions,
)


# ----------------------------------------------------------------------
# _is_page_span  (정확히 길이 2의 int 리스트)
# ----------------------------------------------------------------------

PAGE_SPAN_CASES = [
    ([1, 2], True),
    ([1, 2, 3], False),       # 길이 != 2
    ([1], False),             # 길이 != 2
    ([], False),              # 길이 != 2
    ([1, "x"], False),        # 전부 int 아님
    ("x", False),             # list 아님
    (None, False),            # list 아님
    ([1.0, 2.0], False),      # float 은 int 아님
    ([True, False], True),    # bool 은 int subclass → 통과(의도)
    ([1, True], True),        # 혼합도 통과
]


@pytest.mark.parametrize("value, expected", PAGE_SPAN_CASES)
def test_is_page_span(value: Any, expected: bool) -> None:
    assert _is_page_span(value) is expected


# ----------------------------------------------------------------------
# _is_bbox  (정확히 길이 4의 float-coercible 리스트)
# ----------------------------------------------------------------------

BBOX_CASES = [
    ([1, 2, 3, 4], True),
    ([1.5, 2.5, 3.5, 4.5], True),
    (["1.0", "2", "3", "4"], True),   # float-coercible 문자열 허용
    ([1, 2, 3], False),               # 길이 != 4
    ([1, 2, 3, 4, 5], False),         # 길이 != 4
    ([1, 2, 3, "x"], False),          # float() ValueError arm
    ([1, 2, 3, None], False),         # float(None) TypeError arm (양 except arm 핀)
    ("x", False),                     # list 아님
    (None, False),                    # list 아님
]


@pytest.mark.parametrize("value, expected", BBOX_CASES)
def test_is_bbox(value: Any, expected: bool) -> None:
    assert _is_bbox(value) is expected


# ----------------------------------------------------------------------
# _regions  (list 안의 Mapping 항목만 필터; 그 외 -> [])
# ----------------------------------------------------------------------


def test_regions_filters_non_mappings() -> None:
    assert _regions([{"a": 1}, "x", 5, {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.parametrize(
    "value",
    [
        "x",            # str (list 아님)
        None,           # None
        [],             # 빈 list
        [1, 2, 3],      # Mapping 없음
        ({"a": 1},),    # tuple 은 list 아님 → []
    ],
)
def test_regions_non_list_or_no_mapping_yields_empty(value: Any) -> None:
    assert _regions(value) == []


# ----------------------------------------------------------------------
# _has_region_page  (regions 중 page_number 가 int 인 것 any)
# ----------------------------------------------------------------------

HAS_REGION_PAGE_CASES = [
    ({"regions": [{"page_number": 5}]}, True),
    ({"regions": [{"page_number": "5"}]}, False),          # str 은 int 아님
    ({"regions": [{"page_number": True}]}, True),          # bool 은 int subclass
    ({"regions": [{"x": 1}, {"page_number": 3}]}, True),   # any over 다수
    ({"regions": []}, False),                              # 빈 regions
    ({"regions": "x"}, False),                             # non-list regions → []
    ({}, False),                                           # regions 키 없음
]


@pytest.mark.parametrize("item, expected", HAS_REGION_PAGE_CASES)
def test_has_region_page(item: Any, expected: bool) -> None:
    assert _has_region_page(item) is expected


# ----------------------------------------------------------------------
# _has_region_bbox  (regions 중 유효 bbox any)
# ----------------------------------------------------------------------

HAS_REGION_BBOX_CASES = [
    ({"regions": [{"bbox": [1, 2, 3, 4]}]}, True),
    ({"regions": [{"bbox": [1, 2]}]}, False),   # 무효 bbox(길이)
    ({"regions": [{}]}, False),                 # bbox 키 없음 → _is_bbox(None)
    ({"regions": "x"}, False),                  # non-list regions → []
    ({}, False),                                # regions 키 없음
]


@pytest.mark.parametrize("item, expected", HAS_REGION_BBOX_CASES)
def test_has_region_bbox(item: Any, expected: bool) -> None:
    assert _has_region_bbox(item) is expected


# ----------------------------------------------------------------------
# _has_page_metadata  (page_span 유효 OR region page 존재)
# ----------------------------------------------------------------------

HAS_PAGE_METADATA_CASES = [
    ({"page_span": [1, 2]}, True),                                   # page_span 분기
    ({"regions": [{"page_number": 3}]}, True),                       # region 분기
    # page_span 무효(길이 1)이어도 region 유효 → region 분기로 True
    ({"page_span": [1], "regions": [{"page_number": 7}]}, True),
    # page_span 유효 → regions 무효여도 short-circuit True
    ({"page_span": [1, 2], "regions": "x"}, True),
    # 양쪽 다 무효 → False
    ({"page_span": [1], "regions": [{"page_number": "x"}]}, False),
    ({}, False),
]


@pytest.mark.parametrize("item, expected", HAS_PAGE_METADATA_CASES)
def test_has_page_metadata(item: Any, expected: bool) -> None:
    assert _has_page_metadata(item) is expected
