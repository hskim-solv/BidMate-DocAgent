"""Unit coverage for ``scripts/render_priority_review_boards.py`` 셀 포맷팅 헬퍼.

priority review board 렌더러의 mapping/sequence 정규화 + pct/stat 셀 포맷팅
헬퍼들이다. 보드 셀 숫자 표기 계약(×100 유무·소수 자리·타입 가드)이 조용히
회귀하면 리뷰 보드 수치가 틀어지므로 oracle 로 고정한다. 특히:

- ``_pct_already`` 는 ×100 을 **하지 않고**(12.34 → "12.3%"), ``_metric_mean``
  은 ``_pct`` 경유로 ×100 을 **한다**(0.5 → "50.0%") — 둘의 혼동이 가장 위험.
- ``_number`` 가 bool 을 None 으로 떨어뜨리므로 bool 입력은 모두 "-".
- ``_as_sequence`` 는 str/bytes 를 Sequence 에서 제외한다.

하위 ``_number``/``_pct`` 는 기 커버. 모든 기대값은 소스 실행으로 캡처했다.
``from scripts.render_priority_review_boards import ...`` (implicit namespace).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_priority_review_boards import (
    _as_mapping,
    _as_sequence,
    _mean_cell,
    _metric_mean,
    _pct_already,
    _stat_cell,
)


# ----------------------------------------------------------------------
# _as_mapping / _as_sequence
# ----------------------------------------------------------------------


def test_as_mapping_passes_through_mapping() -> None:
    assert _as_mapping({"a": 1}) == {"a": 1}


@pytest.mark.parametrize("value", [[1], "x", None, 5, (1, 2)])
def test_as_mapping_non_mapping_returns_empty_dict(value: Any) -> None:
    assert _as_mapping(value) == {}


@pytest.mark.parametrize("value", [[1, 2], (1, 2)])
def test_as_sequence_passes_through_real_sequences(value: Any) -> None:
    assert _as_sequence(value) == value


@pytest.mark.parametrize("value", ["abc", b"xy", {"a": 1}, None, 5])
def test_as_sequence_excludes_str_bytes_and_non_sequences(value: Any) -> None:
    # str/bytes 는 Sequence 이지만 의도적으로 제외된다(문자 단위 순회 방지).
    assert _as_sequence(value) == []


# ----------------------------------------------------------------------
# _pct_already  (×100 안 함, .1f)
# ----------------------------------------------------------------------

PCT_ALREADY_CASES = [
    (12.34, "12.3%"),   # ×100 하지 않음 — 1234.0% 가 아니다
    (0, "0.0%"),
    (100, "100.0%"),
    (5, "5.0%"),
    (None, "-"),
    ("x", "-"),         # 비숫자 → "-"
    (True, "-"),        # bool 은 _number 가 None 으로 처리 → "-"
]


@pytest.mark.parametrize("value, expected", PCT_ALREADY_CASES)
def test_pct_already(value: Any, expected: str) -> None:
    assert _pct_already(value) == expected


# ----------------------------------------------------------------------
# _metric_mean  (×100 via _pct)
# ----------------------------------------------------------------------


def test_metric_mean_uses_mean_key_and_scales_by_100() -> None:
    # mapping 에 mean 이 있으면 그 값을 _pct(×100)로 — _pct_already 와 달리 배율이 다르다.
    assert _metric_mean({"mean": 0.5}) == "50.0%"


def test_metric_mean_bare_number_scales_by_100() -> None:
    assert _metric_mean(0.25) == "25.0%"


@pytest.mark.parametrize(
    "metric",
    [
        {"p50": 0.3},      # mean 키 없는 mapping → _pct(dict) → "-"
        None,              # _pct(None) → "-"
        {"mean": None},    # mean 이 None → "-"
    ],
)
def test_metric_mean_missing_or_none_yields_dash(metric: Any) -> None:
    assert _metric_mean(metric) == "-"


# ----------------------------------------------------------------------
# _stat_cell / _mean_cell  (.2f)
# ----------------------------------------------------------------------


def test_stat_cell_default_key_is_p50_two_decimals() -> None:
    assert _stat_cell({"p50": 1.234}) == "1.23"


def test_stat_cell_custom_key() -> None:
    assert _stat_cell({"p90": 2.5}, "p90") == "2.50"


@pytest.mark.parametrize(
    "stats, key",
    [
        ({"p50": 1.0}, "p99"),   # 누락 키 → "-"
        ("x", "p50"),            # non-mapping → "-"
        ({"p50": True}, "p50"),  # bool → _number None → "-"
    ],
)
def test_stat_cell_missing_or_invalid_yields_dash(stats: Any, key: str) -> None:
    assert _stat_cell(stats, key) == "-"


def test_mean_cell_delegates_to_stat_cell_mean_key() -> None:
    assert _mean_cell({"mean": 3.14159}) == "3.14"
    assert _mean_cell({"p50": 1}) == "-"
