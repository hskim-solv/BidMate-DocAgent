"""Unit coverage for ``render_codex_review`` 의 link/sort/finding-render 순수 헬퍼.

Codex adversarial review 마크다운 렌더러는 기존 테스트가 일부 헬퍼만 덮어,
링크 생성·severity 정렬·finding 조립의 경계가 직접 노출되지 않았다. 이 경계가
조용히 회귀하면 리뷰 코멘트의 링크/순서가 깨지거나 malformed payload 에 crash 한다.

- ``_file_link`` 는 repo/sha 둘 다 있어야 GitHub blob URL, 하나라도 falsy 면 plain.
- ``_sort_findings`` 는 SEVERITY_RANK(critical0<high1<medium2<low3, 미지정→low(3),
  미상 severity→99) 1차, file 2차 정렬.
- ``_result_dict`` 는 비-dict result 를 {} 로 degrade (issue #1693 union-gate).
- ``render_finding`` 의 confidence 는 int/float 일 때만 " · confidence X.XX" 로 포맷.

모든 기대값은 pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_codex_review import (
    _file_link,
    _result_dict,
    _sort_findings,
    render_finding,
    render_parse_error,
)


# ----------------------------------------------------------------------
# _file_link — repo AND sha 둘 다 truthy 일 때만 blob URL, 아니면 plain code-span
# ----------------------------------------------------------------------


def test_file_link_full_url_when_repo_and_sha() -> None:
    assert (
        _file_link("o/r", "abc", "f.py", 1, 5)
        == "[`f.py:1-5`](https://github.com/o/r/blob/abc/f.py#L1-L5)"
    )


@pytest.mark.parametrize(
    "repo,sha",
    [
        (None, "abc"),   # repo 없음
        ("o/r", None),   # sha 없음
        ("", "abc"),     # repo falsy(빈 문자열)
        ("o/r", ""),     # sha falsy
    ],
)
def test_file_link_plain_span_when_repo_or_sha_missing(repo: str | None, sha: str | None) -> None:
    assert _file_link(repo, sha, "f.py", 2, 4) == "`f.py:2-4`"


# ----------------------------------------------------------------------
# _sort_findings — severity rank 1차, file 2차
# ----------------------------------------------------------------------


def test_sort_findings_orders_by_severity_rank() -> None:
    findings = [
        {"severity": "low", "file": "a"},
        {"severity": "critical", "file": "z"},
        {"severity": "high", "file": "b"},
        {"severity": "medium", "file": "a"},
    ]
    assert [(f["severity"], f["file"]) for f in _sort_findings(findings)] == [
        ("critical", "z"),
        ("high", "b"),
        ("medium", "a"),
        ("low", "a"),
    ]


def test_sort_findings_missing_severity_defaults_to_low() -> None:
    # severity 키 없음 → "low"(rank 3). critical(0) 이 먼저.
    findings = [{"file": "b"}, {"severity": "critical", "file": "a"}]
    out = _sort_findings(findings)
    assert [f.get("severity", "MISSING") for f in out] == ["critical", "MISSING"]


def test_sort_findings_missing_severity_is_low_not_critical() -> None:
    # 기본값이 "low"(rank 3) 임을 *구분*하는 핀: missing-severity 파일을
    # 알파벳상 먼저(a)로 두면 default-"critical" 가정에선 둘 다 rank 0 → file
    # tie-break 로 missing 이 앞(["MISSING","critical"]). default-"low" 만 critical 을
    # 앞에 유지. (위 테스트는 입력상 양쪽이 같은 출력이라 default 값을 구분 못 함.)
    out = _sort_findings([{"file": "a"}, {"severity": "critical", "file": "z"}])
    assert [f.get("severity", "MISSING") for f in out] == ["critical", "MISSING"]


def test_sort_findings_unknown_severity_ranks_last() -> None:
    # 미상 severity("trivial") → rank 99 → 알려진 low(3) 보다 뒤. file 순서를 압도.
    findings = [{"severity": "trivial", "file": "a"}, {"severity": "low", "file": "b"}]
    assert [f["severity"] for f in _sort_findings(findings)] == ["low", "trivial"]


def test_sort_findings_same_severity_breaks_tie_by_file() -> None:
    findings = [{"severity": "high", "file": "z"}, {"severity": "high", "file": "a"}]
    assert [f["file"] for f in _sort_findings(findings)] == ["a", "z"]


# ----------------------------------------------------------------------
# _result_dict — dict 만 통과, 비-dict → {} (issue #1693)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"result": {"k": 1}}, {"k": 1}),
        ({"result": "str"}, {}),    # 비-dict → {}
        ({"result": None}, {}),
        ({"result": [1]}, {}),      # list 도 비-dict
        ({}, {}),                   # result 키 부재
    ],
)
def test_result_dict(payload: dict[str, Any], expected: dict[str, Any]) -> None:
    assert _result_dict(payload) == expected


# ----------------------------------------------------------------------
# render_parse_error — rawOutput 2000자 절단 + parseError 기본 메시지
# ----------------------------------------------------------------------


def test_render_parse_error_truncates_raw_to_2000() -> None:
    out = render_parse_error({"rawOutput": "X" * 2500, "parseError": "bad"})
    assert "X" * 2000 in out
    assert "X" * 2001 not in out  # 2000자에서 절단
    assert "bad" in out


def test_render_parse_error_default_message_when_missing() -> None:
    out = render_parse_error({})
    assert "(no parseError message)" in out


# ----------------------------------------------------------------------
# render_finding — badge/confidence/recommendation 조립
# ----------------------------------------------------------------------


def test_render_finding_full_assembly() -> None:
    out = render_finding(
        {
            "severity": "high",
            "title": "T",
            "body": "B",
            "recommendation": "R",
            "file": "f.py",
            "line_start": 3,
            "line_end": 5,
            "confidence": 0.9,
        },
        "o/r",
        "sha",
        {"f.py"},
    )
    assert out == (
        "### 🟠 high — T\n"
        "[`f.py:3-5`](https://github.com/o/r/blob/sha/f.py#L3-L5) · confidence 0.90\n"
        "\n"
        "B\n"
        "\n"
        "**Recommendation:** R"
    )


def test_render_finding_unknown_severity_uses_fallback_badge() -> None:
    out = render_finding({"severity": "weird", "file": "f.py"}, None, None, set())
    assert "⚪ weird" in out


def test_render_finding_omits_confidence_when_absent() -> None:
    # confidence 키 없음 → " · confidence" 문자열 미포함.
    out = render_finding({"severity": "low", "file": "f.py"}, None, None, set())
    assert "confidence" not in out


def test_render_finding_omits_confidence_when_non_numeric() -> None:
    # confidence 가 int/float 아님(문자열) → 포맷 생략.
    out = render_finding(
        {"severity": "low", "file": "f.py", "confidence": "high"}, None, None, set()
    )
    assert "confidence" not in out


def test_render_finding_line_defaults_start1_end_equals_start() -> None:
    # line_start 미지정 → 1, line_end 미지정 → line_start 값.
    # (reviewer F2: 기본값 1 / end=start fallback 을 직접 핀해 상수 mutation 을 잡는다.)
    assert "`f.py:1-1`" in render_finding(
        {"severity": "low", "file": "f.py"}, None, None, set()
    )
    # line_start 만 지정 → line_end 가 그 값으로 따라옴.
    assert "`f.py:7-7`" in render_finding(
        {"severity": "low", "file": "f.py", "line_start": 7}, None, None, set()
    )


def test_render_finding_bool_confidence_formats_as_numeric() -> None:
    # bool 은 int 서브클래스 → isinstance(True, (int, float)) True → " · confidence 1.00".
    # (reviewer F3: int/float 게이트가 bool 을 numeric 으로 받는 경계를 핀.)
    assert "confidence 1.00" in render_finding(
        {"severity": "low", "file": "f.py", "confidence": True}, None, None, set()
    )
