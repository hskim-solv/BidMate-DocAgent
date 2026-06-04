"""Unit coverage for ``run_donut_spike`` 의 순수 metric/포맷 헬퍼 7종.

OCR 파이프라인 비교 스파이크는 텍스트 정규화·집합 유사도·필드 P/R·메트릭 집계·
markdown 렌더 헬퍼를 갖지만 전용 단위 테스트가 전무했다(어느 test 도 모듈 import
안 함). 이 메트릭 로직이 조용히 회귀하면 OCR 비교 수치가 왜곡되어도 잡히지 않는다.
아래 경계를 핀한다:

- ``strip_donut_tags`` — 모든 ``<...>`` 태그를 공백으로 치환 후 양끝 strip; **내부**
  공백은 보존(``"<b>bold</b> text"`` → ``"bold  text"``, double space 유지).
- ``tokenize`` — ``lower()`` → 공백 split → 빈 토큰 제거 → ``set``(중복 자동 제거).
- ``jaccard`` — **공집합/공집합은 특수히 1.0**; 그 외 ``|a∩b|/|a∪b|``; 한쪽만 비면 0.0.
- ``coverage`` — non-empty needle 의 stripped substring 매칭 수를 세되, **total 은 빈
  needle 까지 포함한 전체 길이**(``["a","","b"]`` in ``"a x"`` → ``(1, 3)``).
- ``field_pr`` — ``(k, v)`` 를 strip 후 집합화; ``tp/|extracted|`` = precision,
  ``tp/|expected|`` = recall; 어느 쪽이든 비면 그 값 0.0.
- ``compute_metrics`` — ``gt=None`` 분기(원시 count)와 gt 분기(jaccard/coverage/field_pr);
  heading/cell total 0 이면 div-by-zero 가드로 0.0; latency 는 ``round(., 3)``.
- ``render_markdown_table`` — ``gt_available`` 에 따라 2 컬럼 스키마; 누락 키는 빈 셀.

이건 특성화(characterization) 테스트다 — pristine 소스의 **실제 동작**을 핀한다.
모든 기대값은 pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

import pytest

from scripts.run_donut_spike import (
    GroundTruth,
    PipelineResult,
    compute_metrics,
    coverage,
    field_pr,
    jaccard,
    render_markdown_table,
    strip_donut_tags,
    tokenize,
)


# ----------------------------------------------------------------------
# strip_donut_tags — 태그→공백, 양끝 strip, 내부 공백 보존
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<s_title>Hi</s_title>", "Hi"),       # s_ 태그 제거
        ("<b>bold</b> text", "bold  text"),    # 내부 double space 보존 (strip 은 양끝만)
        ("no tags", "no tags"),
        ("  <x>a</x>  ", "a"),                 # 양끝 공백 strip
        ("a<br/>b", "a b"),                    # self-closing 태그도 공백
    ],
)
def test_strip_donut_tags(text: str, expected: str) -> None:
    assert strip_donut_tags(text) == expected


def test_strip_donut_tags_empty_tag_is_preserved() -> None:
    # reviewer M3: `<[^>]+>` 는 브래킷 안에 1자 이상을 요구 → 빈 태그 "<>" 는 매칭 안 되어
    # 그대로 보존된다. `+`→`*` 로 느슨해지면 "<>" 도 삼켜 잡힌다.
    assert strip_donut_tags("a<>b") == "a<>b"


# ----------------------------------------------------------------------
# tokenize — lower → 공백 split → 빈 토큰 제거 → set
# ----------------------------------------------------------------------


def test_tokenize_lowercases_and_dedupes() -> None:
    # 대소문자 정규화 + set 중복 제거: "A a B" → {"a","b"}.
    assert tokenize("A a B") == {"a", "b"}


def test_tokenize_collapses_whitespace_to_empty_set() -> None:
    assert tokenize("   ") == set()


def test_tokenize_splits_on_runs_of_whitespace() -> None:
    assert tokenize("Hello  World") == {"hello", "world"}


# ----------------------------------------------------------------------
# jaccard — 공집합/공집합=1.0 특수, 그 외 |∩|/|∪|, 한쪽만 비면 0.0
# ----------------------------------------------------------------------


def test_jaccard_both_empty_is_one() -> None:
    # 특수 케이스: 둘 다 비면 1.0 (union 분모 0 회피).
    assert jaccard(set(), set()) == 1.0


def test_jaccard_one_empty_is_zero() -> None:
    # 한쪽만 비면 교집합 0, union 비어있지 않음 → 0.0 (1.0 특수와 구분).
    assert jaccard(set(), {"a"}) == 0.0


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ({"a"}, {"a", "b"}, 0.5),
        ({"a"}, {"b"}, 0.0),
        ({"a", "b"}, {"a", "b"}, 1.0),
    ],
)
def test_jaccard_ratio(a: set[str], b: set[str], expected: float) -> None:
    assert jaccard(a, b) == expected


# ----------------------------------------------------------------------
# coverage — matched(non-empty stripped substring), total=전체 needle 수
# ----------------------------------------------------------------------


def test_coverage_total_counts_empty_needles_but_match_skips_them() -> None:
    # "a"만 매칭(1), ""은 스킵, "b"는 미포함 → matched=1; total 은 빈 것 포함 3.
    assert coverage(["a", "", "b"], "a x") == (1, 3)


def test_coverage_all_match() -> None:
    assert coverage(["a", "b"], "a b") == (2, 2)


def test_coverage_empty_list_is_zero_zero() -> None:
    assert coverage([], "x") == (0, 0)


def test_coverage_whitespace_needle_counts_in_total_not_matched() -> None:
    # "  " → strip 후 빈 문자열 → 매칭 안 함(if n.strip()), 그러나 total 엔 포함.
    assert coverage(["  "], "x") == (0, 1)


# ----------------------------------------------------------------------
# field_pr — (k,v) strip 집합, tp/|ext|=p, tp/|exp|=r, 빈 쪽 0.0
# ----------------------------------------------------------------------


def test_field_pr_partial_precision_full_recall() -> None:
    # extracted 2개 중 1개 정답 → p=0.5; expected 1개 전부 맞음 → r=1.0.
    assert field_pr([("k", "v"), ("a", "b")], [("k", "v")]) == (0.5, 1.0)


def test_field_pr_strips_keys_and_values() -> None:
    # 공백 패딩은 strip 후 비교 → 매칭.
    assert field_pr([(" k ", " v ")], [("k", "v")]) == (1.0, 1.0)


@pytest.mark.parametrize(
    "extracted,expected,result",
    [
        ([], [("k", "v")], (0.0, 0.0)),   # extracted 비면 p,r 모두 0.0
        ([("k", "v")], [], (0.0, 0.0)),   # expected 비면 p,r 모두 0.0
    ],
)
def test_field_pr_empty_sides_are_zero(
    extracted: list[tuple[str, str]], expected: list[tuple[str, str]], result: tuple[float, float]
) -> None:
    assert field_pr(extracted, expected) == result


# ----------------------------------------------------------------------
# compute_metrics — gt=None vs gt 분기, div-by-zero 가드, latency round
# ----------------------------------------------------------------------


def _pr() -> PipelineResult:
    return PipelineResult(
        label="L",
        full_text="a b c",
        headings=["H"],
        table_cells=["C"],
        fields=[("k", "v")],
        latency_seconds=1.2345,
    )


def test_compute_metrics_no_ground_truth_emits_raw_counts() -> None:
    m = compute_metrics(_pr(), None)
    assert m == {
        "label": "L",
        "latency_s": 1.234,  # round(1.2345, 3) — banker's rounding
        "error": None,
        "text_chars": 5,
        "headings_found": 1,
        "table_cells_found": 1,
        "fields_found": 1,
    }
    # gt=None 분기엔 recall/precision 키가 없다.
    assert "text_recall_jaccard" not in m


def test_compute_metrics_with_ground_truth_computes_recall_and_pr() -> None:
    gt = GroundTruth(full_text="a b", headings=["H"], table_cells=["Z"], fields=[("k", "v")])
    m = compute_metrics(_pr(), gt)
    # text {a,b,c} vs {a,b} → 2/3 = 0.667; "H" in "a b c"? 아니오 → 0/1; "Z" 미포함 → 0/1.
    assert m["text_recall_jaccard"] == 0.667
    assert m["heading_match"] == "0/1"
    assert m["heading_recall"] == 0.0
    assert m["table_cell_match"] == "0/1"
    assert m["field_p"] == 1.0
    assert m["field_r"] == 1.0


def test_compute_metrics_heading_and_cell_coverage_not_swapped() -> None:
    # reviewer M18: 기존 테스트는 heading/cell 이 대칭(둘 다 0/1)이라 두 coverage(...) 인자
    # 라인을 맞바꿔도 안 잡힌다. 비대칭 GT(heading 은 본문에 존재, cell 은 부재)로 두 채널을
    # 분리 핀 → heading/cell 인자 swap regression(메트릭 오라벨)을 잡는다.
    pr = PipelineResult("L", "Overview", [], [], [], 0.0)
    gt = GroundTruth(full_text="x", headings=["Overview"], table_cells=["Missing"], fields=[])
    m = compute_metrics(pr, gt)
    assert m["heading_match"] == "1/1"
    assert m["heading_recall"] == 1.0
    assert m["table_cell_match"] == "0/1"
    assert m["table_cell_recall"] == 0.0


def test_compute_metrics_zero_total_recall_guarded_to_zero() -> None:
    # gt 의 headings/table_cells 가 비면 total 0 → div-by-zero 가드로 0.0.
    gt0 = GroundTruth(full_text="x", headings=[], table_cells=[], fields=[])
    m = compute_metrics(_pr(), gt0)
    assert m["heading_recall"] == 0.0
    assert m["table_cell_recall"] == 0.0


# ----------------------------------------------------------------------
# render_markdown_table — gt_available 별 스키마, 누락 키 빈 셀
# ----------------------------------------------------------------------


def test_render_markdown_table_gt_schema() -> None:
    # reviewer M22: field_p/field_r 을 **구별되는** 값(0.9 vs 0.1)으로 둬, 두 컬럼이 같은
    # 키를 읽도록 바뀌는 swap mutation 을 잡는다(둘 다 1.0 이면 swap 이 보이지 않음).
    out = render_markdown_table(
        [
            {
                "label": "row1",
                "text_recall_jaccard": 0.5,
                "heading_match": "1/1",
                "table_cell_match": "0/1",
                "field_p": 0.9,
                "field_r": 0.1,
                "latency_s": 1.2,
            }
        ],
        True,
    )
    lines = out.splitlines()
    assert lines[0] == "| Metric | text_recall | heading_match | table_cell_match | field_p | field_r | latency_s |"
    assert lines[1] == "| --- | --- | --- | --- | --- | --- | --- |"
    assert lines[2] == "| row1 | 0.5 | 1/1 | 0/1 | 0.9 | 0.1 | 1.2 |"


def test_render_markdown_table_no_gt_schema_and_missing_keys_blank() -> None:
    out = render_markdown_table([{"label": "r", "text_chars": 10}], False)
    lines = out.splitlines()
    assert lines[0] == "| Metric | text_chars | headings_found | table_cells_found | fields_found | latency_s |"
    # 누락 키(headings_found 등)는 row.get(k, "") → 빈 셀.
    assert lines[2] == "| r | 10 |  |  |  |  |"
