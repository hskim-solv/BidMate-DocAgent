"""Unit coverage for ``render_adr_decision_map`` 의 분류·정형 헬퍼 3종.

board 빌더는 기존 테스트가 상위(`parse_adr_index`/`build_board`/`render_html`)로
덮지만, ADR 엔트리를 status-family / area 로 분류하고 행으로 정형하는 순수 헬퍼는
직접 커버리지가 없었다. 이 분류는 **first-match priority + case-insensitive
substring** 이라, 검사 순서가 조용히 바뀌면 decision map 의 상태/영역 집계가
왜곡된다.

이건 특성화(characterization) 테스트다 — "정답"이 아니라 pristine 소스의 **실제
동작**을 핀한다. 특히 substring 으로 인한 두 가지 직관-위배 분류를 명시적으로
고정한다:

- ``_area_for("retrieval ...")`` → ``"eval / measurement"`` — "retrieval" 이
  "eval" 을 substring 으로 포함(r-e-t-r-i-**e-v-a-l**)하고 eval 그룹이 먼저 검사됨.
- ``_area_for("prompt injection ...")`` → ``"governance"`` — "prompt" 이 "pr" 을
  포함하고 governance 그룹("...pr...")이 security 그룹보다 먼저 검사됨.

모든 기대값은 pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

import pytest

from scripts.render_adr_decision_map import (
    AdrEntry,
    _area_for,
    _entry_rows,
    _status_family,
)


# ----------------------------------------------------------------------
# _status_family — first-match priority: superseded > deprecated > accepted > proposed
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        ("Accepted", "accepted"),
        ("Proposed", "proposed"),
        ("Superseded by 0099", "superseded"),
        ("Deprecated", "deprecated"),
        ("SUPERSEDED", "superseded"),  # case-insensitive (lower() 후 substring)
        ("Rejected", "other"),         # 매칭 family 없음 → fallback
        ("", "other"),
    ],
)
def test_status_family(status: str, expected: str) -> None:
    assert _status_family(status) == expected


def test_status_family_priority_superseded_beats_accepted() -> None:
    # 두 키워드 공존 시 먼저 검사되는 쪽이 이긴다 (superseded 가 accepted 보다 먼저).
    assert _status_family("accepted, later superseded") == "superseded"


def test_status_family_priority_deprecated_beats_accepted() -> None:
    assert _status_family("deprecated and accepted") == "deprecated"


def test_status_family_priority_accepted_beats_proposed() -> None:
    assert _status_family("proposed then accepted") == "accepted"


# ----------------------------------------------------------------------
# _area_for — first-match priority over 7 keyword 그룹 + fallback
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("metric real benchmark", "eval / measurement"),  # eval 그룹
        ("bm25 chunking", "retrieval"),                   # retrieval (eval substring 없음)
        ("embedding model", "retrieval"),
        ("pdf page parser", "ingestion"),
        ("codex workflow", "agent workflow"),
        ("branch governance", "governance"),
        ("evidence citation", "answer / evidence"),
        ("pii leak", "security"),                         # 깨끗한 security (shadow 없음)
        ("injection vector", "security"),
        ("misc thing", "foundation / other"),             # fallback
    ],
)
def test_area_for_clean_groups(text: str, expected: str) -> None:
    assert _area_for(text) == expected


def test_area_for_retrieval_word_is_shadowed_by_eval_substring() -> None:
    # "retrieval" 자체가 "eval" 을 포함 → eval 그룹이 먼저 잡아 "eval / measurement".
    # 이 substring shadowing 이 핵심 특성. (검사 순서 reorder 회귀를 잡는다.)
    assert _area_for("retrieval reranker") == "eval / measurement"


def test_area_for_prompt_is_shadowed_by_pr_governance_substring() -> None:
    # "prompt" 이 "pr"(governance 그룹) 을 포함 → security 보다 governance 가 먼저.
    assert _area_for("prompt injection security") == "governance"


def test_area_for_is_case_insensitive() -> None:
    assert _area_for("EVAL HARNESS") == "eval / measurement"


@pytest.mark.parametrize(
    "keyword,expected",
    [
        # eval / measurement 그룹 — 각 키워드 isolation (drop 시 fallback 으로 떨어짐)
        ("eval", "eval / measurement"),
        ("real", "eval / measurement"),
        ("benchmark", "eval / measurement"),
        ("metric", "eval / measurement"),
        ("judge", "eval / measurement"),
        ("retrieval", "eval / measurement"),  # substring shadow (eval ⊂ retrieval)
        # retrieval 그룹
        ("embedding", "retrieval"),
        ("rerank", "retrieval"),
        ("bm25", "retrieval"),
        ("chunk", "retrieval"),
        # ingestion 그룹
        ("hwp", "ingestion"),
        ("pdf", "ingestion"),
        ("parser", "ingestion"),
        ("ingestion", "ingestion"),
        ("page", "ingestion"),
        # agent workflow 그룹
        ("agent", "agent workflow"),
        ("langgraph", "agent workflow"),
        ("workflow", "agent workflow"),
        ("codex", "agent workflow"),
        # governance 그룹
        ("governance", "governance"),
        ("branch", "governance"),
        ("pr", "governance"),
        ("hook", "governance"),
        # answer / evidence 그룹
        ("answer", "answer / evidence"),
        ("citation", "answer / evidence"),
        ("verifier", "answer / evidence"),
        ("evidence", "answer / evidence"),
        # security 그룹
        ("security", "security"),
        ("injection", "security"),
        ("pii", "security"),
    ],
)
def test_area_for_each_keyword_is_load_bearing(keyword: str, expected: str) -> None:
    # reviewer F1: 그룹당 키워드 1개만 테스트하면 나머지 키워드 drop mutation 이 생존.
    # 각 키워드를 isolation 으로 핀 → 어느 키워드를 그룹 튜플에서 제거해도 잡힌다.
    assert _area_for(keyword) == expected


# ----------------------------------------------------------------------
# _entry_rows — AdrEntry → 행, {number:04d} zero-pad, 컬럼 순서 고정
# ----------------------------------------------------------------------


def test_entry_rows_zero_pads_number_and_orders_columns() -> None:
    entry = AdrEntry(number=7, link="docs/adr/0007.md", status="Accepted", area="governance", title="Branch conv")
    # 컬럼 순서: number(04d), status, area, title, link (AdrEntry 필드 순서와 다름).
    assert _entry_rows([entry]) == [["0007", "Accepted", "governance", "Branch conv", "docs/adr/0007.md"]]


def test_entry_rows_handles_multiple_and_wider_numbers() -> None:
    entries = [
        AdrEntry(number=7, link="a.md", status="Accepted", area="x", title="T7"),
        AdrEntry(number=123, link="b.md", status="Proposed", area="y", title="T123"),
    ]
    assert _entry_rows(entries) == [
        ["0007", "Accepted", "x", "T7", "a.md"],
        ["0123", "Proposed", "y", "T123", "b.md"],  # 4자리 초과는 그대로 (자르지 않음)
    ]


def test_entry_rows_empty_is_empty_list() -> None:
    assert _entry_rows([]) == []
