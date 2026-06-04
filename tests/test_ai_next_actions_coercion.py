"""Unit coverage for ``scripts/ai_next_actions.py`` 숫자 coercion 헬퍼.

``_as_int`` / ``_nested_int`` / ``_nested_float`` 는 gh JSON·리포트 dict 처럼
느슨하게 타이핑된 페이로드에서 정수/실수를 안전 추출한다(예외 흡수 → default 또는
None). 직접 단위 테스트가 없어 다음을 oracle 로 고정한다:

- ``_as_int``: int()의 동작(공백 strip, float 절삭, bool→1, **float 문자열은
  미파싱**)과 TypeError/ValueError 흡수 → default
- ``_nested_int``/``_nested_float``: path mapping walk, 중간 단락/누락키/최종
  None·비숫자 → None, **빈 path → None**(컨테이너 자체를 변환 시도)

``scripts/`` 는 repo 루트에서 도달 가능한 implicit namespace package 라
``from scripts.ai_next_actions import ...`` 로 import 한다. 모든 기대값은 소스
실행으로 캡처했다.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.ai_next_actions import _as_int, _nested_int, _nested_float


# (value, default, expected)
AS_INT_CASES = [
    (5, 0, 5),
    ("7", 0, 7),
    ("  10  ", 0, 10),      # int() 가 공백을 strip
    (3.9, 0, 3),            # float 는 0 방향으로 절삭
    (True, 0, 1),           # bool 은 int 의 하위형 → 1
    (None, 0, 0),           # TypeError → default
    ("x", 0, 0),            # ValueError → default
    ("", 0, 0),             # ValueError → default
    ("1.5", 0, 0),          # int() 는 float 문자열을 파싱하지 않음 → default
    ("x", -1, -1),          # custom default 반영
]


@pytest.mark.parametrize("value, default, expected", AS_INT_CASES)
def test_as_int(value: Any, default: int, expected: int) -> None:
    result = _as_int(value, default)
    assert result == expected
    assert isinstance(result, int)


def test_as_int_default_is_zero() -> None:
    # default 인자 생략 시 0.
    assert _as_int("not-a-number") == 0


# (payload, path, expected)
NESTED_INT_CASES = [
    ({"a": {"b": "5"}}, ["a", "b"], 5),       # 정상 walk + 문자열 int
    ({"a": 5}, ["a", "b"], None),             # 중간 값이 mapping 이 아님 → None
    ({"a": {"b": None}}, ["a", "b"], None),   # 최종 None → None
    ({"a": {"b": "x"}}, ["a", "b"], None),    # 비정수 → None
    ({"a": {}}, ["a", "b"], None),            # 누락 키 → None
    ({"a": 1}, [], None),                     # 빈 path → 컨테이너 자체 int() → None
    ({"a": {"b": 3.9}}, ["a", "b"], 3),       # float 절삭
    ({"a": {"b": True}}, ["a", "b"], 1),      # bool → 1
]


@pytest.mark.parametrize("payload, path, expected", NESTED_INT_CASES)
def test_nested_int(payload: dict, path: list[str], expected: int | None) -> None:
    assert _nested_int(payload, path) == expected


# (payload, path, expected)
NESTED_FLOAT_CASES = [
    ({"a": {"b": "1.5"}}, ["a", "b"], 1.5),   # 문자열 float
    ({"a": {"b": 2}}, ["a", "b"], 2.0),       # int → float
    ({"a": 5}, ["a", "b"], None),             # 중간 단락 → None
    ({"a": {"b": None}}, ["a", "b"], None),   # 최종 None → None
    ({"a": {"b": "x"}}, ["a", "b"], None),    # 비숫자 → None
    ({"a": {}}, ["a", "b"], None),            # 누락 키 → None (.get vs [] 회귀 가드)
    ({"x": 1}, [], None),                     # 빈 path → None
]


@pytest.mark.parametrize("payload, path, expected", NESTED_FLOAT_CASES)
def test_nested_float(payload: dict, path: list[str], expected: float | None) -> None:
    result = _nested_float(payload, path)
    assert result == expected
    if expected is not None:
        assert isinstance(result, float)


def test_nested_int_returns_none_not_default_on_break() -> None:
    # _as_int 와 달리 _nested_int 는 실패 시 default(0)가 아니라 None 을 돌려준다
    # (missing vs numeric-zero 를 구분하는 호출부 계약).
    assert _nested_int({"a": {}}, ["a", "b"]) is None


def test_nested_walk_does_not_coerce_intermediate_container() -> None:
    # 빈 path 는 최종 값이 컨테이너(dict)인 채로 변환을 시도해 None 으로 떨어진다.
    assert _nested_int({"k": 1}, []) is None
    assert _nested_float({"k": 1}, []) is None
