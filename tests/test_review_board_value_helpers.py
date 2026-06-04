"""Unit coverage for ``render_priority_review_boards`` 의 값/포맷 순수 헬퍼 8종.

priority review board 렌더러는 기존 테스트가 상위 진입점(``main``/``render_all``/
``render_eval_history``)과 cell-formatting 일부(``_as_mapping``/``_as_sequence``/
``_mean_cell``/``_metric_mean``/``_pct_already``/``_stat_cell``)만 덮는다. 나머지
무부작용 값/포맷 변환 헬퍼 8종은 직접 커버리지가 없어, 아래 미묘한 경계가 조용히
회귀해도 잡히지 않는다:

- ``_number`` — ``bool`` 은 ``int`` 서브클래스라 가드 없으면 ``True``→``1.0`` 로 새는데,
  명시적 ``isinstance(value, bool)`` 가드로 ``None`` 을 돌려준다.
- ``_cell`` — ``bool`` 검사가 ``str`` 변환보다 **먼저** 라 ``True``→``"yes"``(``"True"`` 아님).
- ``_pct`` 는 ×100(``0.25``→``"25.0%"``), ``_pct_already``(기존 커버)는 raw — 둘을 혼동하면 100배 왜곡.
- ``_delta`` 는 ``abs<1`` 이고 **과학표기(e)가 아닐 때만** 3-decimal, 그 외 2-decimal.
  ``1e-05`` 는 절댓값이 1 미만이어도 ``"e"`` 가드에 걸려 ``"+0.00"``.
- ``_top_counter_rows`` 는 ``_number(value) or 0`` 키로 내림차순 — 비숫자 값은 0 으로 침몰.
- ``_markdown_headings`` 는 ``"## "`` prefix 라인만, prefix 제거 후 strip (빈 heading ``""`` 포함).
- ``_metric_from_nested`` 는 중첩 key walk — 중간이 mapping 이 아니면 이후 전부 ``None``.

이건 특성화(characterization) 테스트다 — pristine 소스의 **실제 동작**을 핀한다.
모든 기대값은 pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_priority_review_boards import (
    _cell,
    _delta,
    _markdown_headings,
    _markdown_table,
    _metric_from_nested,
    _number,
    _pct,
    _top_counter_rows,
)


# ----------------------------------------------------------------------
# _number — bool→None(int 서브클래스 가드), int/float→float, 그 외→None
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (5, 5.0),
        (2.5, 2.5),
        (0, 0.0),       # falsy int 도 float 으로 통과
        (-3, -3.0),
        ("3", None),    # 숫자 문자열은 강제하지 않음
        (None, None),
        ([1], None),
    ],
)
def test_number_coercion(value: Any, expected: float | None) -> None:
    assert _number(value) == expected


@pytest.mark.parametrize("value", [True, False])
def test_number_bool_is_none_not_numeric(value: bool) -> None:
    # bool 은 int 서브클래스 → 가드 없으면 True→1.0/False→0.0 으로 샌다.
    # 명시 가드가 None 을 돌려주는 게 핵심 — 이 핀이 bool-가드 drop mutation 을 잡는다.
    assert _number(value) is None


# ----------------------------------------------------------------------
# _cell — None→"-", bool→yes/no(str 보다 먼저), 그 외→str
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "-"),
        (True, "yes"),    # bool 검사가 str() 보다 먼저 → "True" 아님
        (False, "no"),
        (5, "5"),
        (0, "0"),         # int 0 은 None 도 bool 도 아님 → str → "0"
        (2.5, "2.5"),
        ("x", "x"),
    ],
)
def test_cell(value: Any, expected: str) -> None:
    assert _cell(value) == expected


# ----------------------------------------------------------------------
# _pct — ×100 후 1-decimal %, None→"-"
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.25, "25.0%"),   # ×100
        (1, "100.0%"),
        (0, "0.0%"),
        (0.005, "0.5%"),   # 1-decimal 반올림
    ],
)
def test_pct_scales_by_100(value: Any, expected: str) -> None:
    assert _pct(value) == expected


@pytest.mark.parametrize("value", [None, "x", True])
def test_pct_non_number_yields_dash(value: Any) -> None:
    # _number 가 None 을 돌려주는 입력(None/문자열/bool) → "-".
    assert _pct(value) == "-"


# ----------------------------------------------------------------------
# _delta — abs<1 & 비과학표기 → +.3f, 그 외 → +.2f. None → "-"
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.5, "+0.500"),    # abs<1, no e → 3-decimal, 부호 명시
        (-0.5, "-0.500"),
        (0.0, "+0.000"),
        (0.9999, "+1.000"), # 반올림되어도 3-decimal 포맷 유지
        (1.5, "+1.50"),     # abs>=1 → 2-decimal
        (-2.0, "-2.00"),
    ],
)
def test_delta_decimal_width_by_magnitude(value: Any, expected: str) -> None:
    assert _delta(value) == expected


def test_delta_scientific_notation_forces_two_decimals() -> None:
    # 1e-05 는 절댓값 1 미만이지만 str(value)="1e-05" 에 "e" 가 있어 3-decimal 분기에서 탈락
    # → 2-decimal "+0.00". 이 "e" 가드가 빠지면 "+0.000" 이 되어 mutation 이 잡힌다.
    assert _delta(1e-05) == "+0.00"


@pytest.mark.parametrize("value,expected", [(1.0, "+1.00"), (-1.0, "-1.00"), (1, "+1.00")])
def test_delta_boundary_at_one_uses_two_decimals(value: Any, expected: str) -> None:
    # reviewer M4d: 경계 비교가 `abs<1` (strict) 임을 핀한다. 정확히 ±1.0 은 3-decimal
    # 분기에 들지 않고 2-decimal. `<` 가 `<=` 로 바뀌면 "+1.000" 이 되어 잡힌다.
    assert _delta(value) == expected


@pytest.mark.parametrize("value", [None, "x"])
def test_delta_non_number_yields_dash(value: Any) -> None:
    assert _delta(value) == "-"


# ----------------------------------------------------------------------
# _top_counter_rows — _number(value) or 0 키 내림차순, top limit
# ----------------------------------------------------------------------


def test_top_counter_rows_sorts_desc_by_numeric_value() -> None:
    assert _top_counter_rows({"a": 3, "b": 1, "c": 2}) == [["a", 3], ["c", 2], ["b", 1]]


def test_top_counter_rows_respects_limit() -> None:
    assert _top_counter_rows({"a": 3, "b": 1, "c": 2}, limit=2) == [["a", 3], ["c", 2]]


def test_top_counter_rows_non_numeric_value_sinks_to_zero() -> None:
    # 'x' → _number None → `or 0` → 0 < 2 → b 가 먼저, a 가 뒤. 값은 원본 그대로 유지.
    assert _top_counter_rows({"a": "x", "b": 2}) == [["b", 2], ["a", "x"]]


def test_top_counter_rows_non_numeric_fallback_is_zero_not_one() -> None:
    # reviewer M5b: 위 테스트는 경쟁값이 2 라 `or 0` 든 `or 1` 든 b 가 앞 → fallback 상수를
    # 구분 못 한다. (0,1) 구간의 경쟁값 0.5 로 핀: `or 0` 이면 0<0.5 → b 먼저,
    # `or 1` 이면 1>0.5 → a 먼저. 이 입력만이 fallback 이 0 임을 증명한다.
    assert _top_counter_rows({"a": "x", "b": 0.5}) == [["b", 0.5], ["a", "x"]]


def test_top_counter_rows_empty_is_empty_list() -> None:
    assert _top_counter_rows({}) == []


# ----------------------------------------------------------------------
# _markdown_table — 헤더 매칭 행 추출, |--- skip, 비-| 라인서 종료
# ----------------------------------------------------------------------


def test_markdown_table_extracts_rows_under_matching_header() -> None:
    md = (
        "intro\n"
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
        "trailing text\n"
    )
    assert _markdown_table(md, ["A", "B"]) == [["1", "2"], ["3", "4"]]


def test_markdown_table_returns_empty_when_header_absent() -> None:
    md = "| X | Y |\n|---|---|\n| 1 | 2 |\n"
    assert _markdown_table(md, ["A", "B"]) == []


def test_markdown_table_truncates_extra_cells_to_header_count() -> None:
    # 셀이 헤더보다 많으면 헤더 수만큼만 취한다 (len >= 헤더수 게이트 통과 후 slice).
    md = "| A | B |\n|---|---|\n| 1 | 2 | 3 |\n"
    assert _markdown_table(md, ["A", "B"]) == [["1", "2"]]


def test_markdown_table_breaks_on_non_pipe_line() -> None:
    # reviewer M6b: 비-| 라인을 만나면 `break` 로 즉시 종료 → 이후 | 행은 수집 안 함.
    # `break` 가 `continue` 로 바뀌면 "NOT A ROW" 를 건너뛰고 "| 3 | 4 |" 까지 잘못 수집한다.
    md = "| A | B |\n|---|---|\n| 1 | 2 |\nNOT A ROW\n| 3 | 4 |\n"
    assert _markdown_table(md, ["A", "B"]) == [["1", "2"]]


# ----------------------------------------------------------------------
# _markdown_headings — "## " prefix 라인, prefix 제거 후 strip (빈 heading 포함)
# ----------------------------------------------------------------------


def test_markdown_headings_level2_extracts_and_strips() -> None:
    md = "## Alpha\ntext\n## Beta \n### Gamma\n#NoSpace\n## "
    # "## Beta " → strip → "Beta"; "### Gamma"/"#NoSpace" 제외; 마지막 "## " → ""(빈 heading 포함).
    assert _markdown_headings(md) == ["Alpha", "Beta", ""]


def test_markdown_headings_custom_level() -> None:
    md = "## Alpha\n### Gamma\n### Delta\n"
    assert _markdown_headings(md, level="###") == ["Gamma", "Delta"]


# ----------------------------------------------------------------------
# _metric_from_nested — 중첩 key walk, 중간이 mapping 아니면 이후 None
# ----------------------------------------------------------------------


def test_metric_from_nested_walks_full_path() -> None:
    assert _metric_from_nested({"a": {"b": {"c": 7}}}, "a", "b", "c") == 7


def test_metric_from_nested_returns_intermediate_mapping() -> None:
    assert _metric_from_nested({"a": {"b": {"c": 7}}}, "a", "b") == {"c": 7}


@pytest.mark.parametrize(
    "keys",
    [
        ("a", "x", "c"),  # 중간 key 부재 → None.get 연쇄
        ("z",),           # 첫 key 부재
    ],
)
def test_metric_from_nested_broken_path_is_none(keys: tuple[str, ...]) -> None:
    assert _metric_from_nested({"a": {"b": {"c": 7}}}, *keys) is None


def test_metric_from_nested_non_mapping_intermediate_is_none() -> None:
    # current 가 mapping 아님(int 5) → _as_mapping 이 {} 로 강등 → .get("b") None.
    assert _metric_from_nested({"a": 5}, "a", "b") is None
