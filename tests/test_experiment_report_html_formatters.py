"""Unit coverage for ``render_experiment_report_html`` 의 순수 HTML 포맷 헬퍼 6종.

실험 리포트 HTML 렌더러는 기존 테스트(``test_render_experiment_report_html.py``)가
top-level ``render_html`` end-to-end(HTML escape + raw_results/data_list/chunk_text 키
privacy-deny 가드 + stale-pair 감지)만 덮는다. 내부 순수 포맷 헬퍼 6종은 직접
커버리지가 없어, 아래 경계가 조용히 회귀해도 잡히지 않는다:

- ``_truncate`` — 2000자 **초과**일 때만 절단(``s[:2000] + "… [truncated N chars]"``);
  정확히 2000자는 그대로(strict ``>``).
- ``_tone_for_metric`` — accuracy/recall/precision 을 substring 으로 포함할 때만 임계값
  판정(``>=0.7`` ok / ``>=0.4`` warn / 그 외 danger), 그 외 메트릭은 mean 무관 neutral.
  ``.lower()`` 후 비교라 대소문자 무관.
- ``_render_markdown_body`` — 첫 ``"# "`` 라인에서 제목 추출(**첫 매치서 break**); ``"# "``
  prefix 라인이 없으면(무-h1, ``"## "``/``"#tag"``, 또는 strip 후 ``"#"`` 가 되는 ``"# "``)
  기본값 ``"REPORT.md"`` 유지, body 는 HTML escape. (소스의 ``or title`` 분기는 루프가
  ``line.strip()`` 을 쓰므로 stripped 라인이 정확히 ``"# "`` 가 될 수 없어 도달 불가 —
  fallback 은 항상 기본값 미재할당 경로로 일어난다.)
- ``_render_kv_grid`` — dict/list 값은 카드에서 스킵, 전부 스킵되면 빈 문자열.
- ``_render_generic_table`` — key 정렬, 빈 입력은 ``"empty"`` 메시지.
- ``_render_ci_table`` — 비-dict stats 스킵, 빈/전부-스킵이면 ``"no CI block"``.

table 렌더러 3종은 ``html_report`` 출력 마크업을 정확히 매칭하지 않고(취약), 헬퍼
**자체 로직**(필터/정렬/빈-처리)만 robust substring 으로 핀한다. 모든 기대값은
pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

import pytest

from scripts.render_experiment_report_html import (
    VALUE_TRUNCATE_CHARS,
    _render_ci_table,
    _render_generic_table,
    _render_kv_grid,
    _render_markdown_body,
    _tone_for_metric,
    _truncate,
)


# ----------------------------------------------------------------------
# _truncate — strict > 2000 일 때만 절단, 그 외 str(value) 그대로
# ----------------------------------------------------------------------


def test_truncate_short_value_passthrough() -> None:
    assert _truncate("abc") == "abc"


def test_truncate_non_str_is_stringified() -> None:
    assert _truncate(123) == "123"


def test_truncate_at_limit_is_not_truncated() -> None:
    # 정확히 2000자(경계)는 `>` 가 strict 라 절단 안 함 → 길이 보존, 마커 없음.
    s = "y" * VALUE_TRUNCATE_CHARS
    out = _truncate(s)
    assert out == s
    assert "truncated" not in out


def test_truncate_over_limit_appends_marker_with_original_length() -> None:
    n = VALUE_TRUNCATE_CHARS + 5
    out = _truncate("x" * n)
    assert out.startswith("x" * VALUE_TRUNCATE_CHARS)
    assert out.endswith(f"… [truncated {n} chars]")
    # 절단 본문은 정확히 2000자 + 마커.
    assert out[:VALUE_TRUNCATE_CHARS] == "x" * VALUE_TRUNCATE_CHARS
    assert out[VALUE_TRUNCATE_CHARS] != "x"


# ----------------------------------------------------------------------
# _tone_for_metric — 관련 메트릭만 임계값, 그 외 neutral. 대소문자 무관.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,mean,expected",
    [
        ("accuracy", 0.7, "ok"),       # >=0.7 경계
        ("accuracy", 0.69, "warn"),    # 0.7 미만 → warn
        ("recall", 0.4, "warn"),       # >=0.4 경계
        ("recall", 0.39, "danger"),    # 0.4 미만 → danger
        ("precision", 0.95, "ok"),
        ("precision", 0.0, "danger"),
    ],
)
def test_tone_for_relevant_metric_thresholds(name: str, mean: float, expected: str) -> None:
    assert _tone_for_metric(name, mean) == expected


def test_tone_is_case_insensitive() -> None:
    # name.lower() 후 substring 검사 → 대문자 "Accuracy" 도 동일 분기.
    assert _tone_for_metric("Accuracy", 0.5) == "warn"


@pytest.mark.parametrize("mean", [0.0, 0.5, 0.99])
def test_tone_for_unrelated_metric_is_neutral_regardless_of_mean(mean: float) -> None:
    # accuracy/recall/precision substring 없으면 mean 과 무관하게 neutral.
    assert _tone_for_metric("latency", mean) == "neutral"


def test_tone_substring_match_not_exact() -> None:
    # "top_accuracy" 처럼 substring 포함이면 관련 메트릭으로 취급(정확 일치 아님).
    assert _tone_for_metric("top_accuracy", 0.8) == "ok"


# ----------------------------------------------------------------------
# _render_markdown_body — 첫 "# " 제목 추출(break), fallback "REPORT.md", escape
# ----------------------------------------------------------------------


def test_markdown_title_from_first_h1() -> None:
    title, _ = _render_markdown_body("intro\n# Title Here\nmore")
    assert title == "Title Here"


def test_markdown_title_first_h1_wins() -> None:
    # 첫 "# " 에서 break → 두 번째 제목은 무시.
    title, _ = _render_markdown_body("# First\n# Second")
    assert title == "First"


@pytest.mark.parametrize("text", ["plain text\nno heading", "# \nbody"])
def test_markdown_title_falls_back_to_report_md(text: str) -> None:
    # 무-h1, 또는 빈 제목 "# "(strip 후 "#" → startswith("# ") 실패) → 제목 미추출
    # → 기본값 "REPORT.md" 유지. (소스 `or title` 분기는 도달 불가 — docstring 참조.)
    title, _ = _render_markdown_body(text)
    assert title == "REPORT.md"


def test_markdown_title_ignores_non_h1_headings() -> None:
    # reviewer M12: "## "/"#tag" 는 "# "(h1) 가 아니다 → 제목 미추출 → fallback.
    # startswith("# ") 가 startswith("#") 로 느슨해지면 "Subhead" 가 새어 잡힌다.
    assert _render_markdown_body("## Subhead\nbody")[0] == "REPORT.md"
    assert _render_markdown_body("#tag\nbody")[0] == "REPORT.md"


def test_markdown_body_escapes_html() -> None:
    _, body = _render_markdown_body("<b>danger</b>")
    assert "&lt;b&gt;" in body
    assert "<b>danger</b>" not in body


# ----------------------------------------------------------------------
# _render_kv_grid — dict/list 값 스킵, 전부 스킵 시 빈 문자열
# ----------------------------------------------------------------------


def test_kv_grid_empty_dict_is_empty_string() -> None:
    assert _render_kv_grid({}) == ""


def test_kv_grid_all_complex_values_is_empty_string() -> None:
    # 모든 값이 dict/list → 카드 0 → "".
    assert _render_kv_grid({"a": {"x": 1}, "b": [1, 2]}) == ""


def test_kv_grid_skips_dict_and_list_keeps_scalars() -> None:
    out = _render_kv_grid({"scalar_key": 1, "dict_key": {"x": 1}, "list_key": [1]})
    assert "scalar_key" in out
    assert "dict_key" not in out
    assert "list_key" not in out


# ----------------------------------------------------------------------
# _render_generic_table — key 정렬, 빈 입력 empty 메시지
# ----------------------------------------------------------------------


def test_generic_table_empty_shows_empty_message() -> None:
    # reviewer M19: `"empty" in out` 는 render_table 의 항상-존재 `class="empty"` 에도
    # 걸려 부분 vacuous. empty_message **셀 내용**(`>empty<`)을 핀해야 헬퍼가 넘긴
    # 메시지 인자를 실제로 검증한다.
    assert ">empty<" in _render_generic_table({})


def test_generic_table_sorts_keys() -> None:
    out = _render_generic_table({"zz": 1, "aa": 2})
    assert out.index("aa") < out.index("zz")


# ----------------------------------------------------------------------
# _render_ci_table — 비-dict stats 스킵, 빈/전부-스킵 시 "no CI block"
# ----------------------------------------------------------------------


def test_ci_table_empty_shows_no_ci_block() -> None:
    assert "no CI block" in _render_ci_table({})


def test_ci_table_non_dict_stats_are_skipped() -> None:
    # stats 가 dict 아님 → continue → 행 0 → empty 메시지.
    assert "no CI block" in _render_ci_table({"metric_a": "not-a-dict", "metric_b": 5})


def test_ci_table_renders_metric_with_dict_stats() -> None:
    # dict stats 면 metric 이름이 출력에 등장(행 생성).
    out = _render_ci_table({"accuracy": {"mean": 0.5, "ci_lo": 0.4, "ci_hi": 0.6, "n": 10}})
    assert "accuracy" in out
    assert "no CI block" not in out


def test_ci_table_formats_mean_and_bounds_4_decimals_with_tone() -> None:
    # reviewer M21/M23/M24: 행-존재만 보던 테스트가 mean .4f 포맷·mean/ci_lo/ci_hi 키 계약·
    # mean→tone 바인딩을 미검증으로 두었다. 한 행을 렌더해 셋을 동시에 핀한다:
    #   - mean .4f → "0.5000" (`.2f` 로 바뀌면 탈락)
    #   - ci_lo/ci_hi 키 → "[0.4000, 0.6000]" (키 오독 시 "—")
    #   - mean 0.5 → _tone_for_metric("accuracy",0.5)=warn → render_badge "badge warn"
    #     (mean 키 오독 시 mean=None → neutral)
    out = _render_ci_table({"accuracy": {"mean": 0.5, "ci_lo": 0.4, "ci_hi": 0.6, "n": 10}})
    assert "0.5000" in out
    assert "[0.4000, 0.6000]" in out
    assert "badge warn" in out
