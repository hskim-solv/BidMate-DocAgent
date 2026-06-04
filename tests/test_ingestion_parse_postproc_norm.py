"""Unit coverage for ingestion.py 파싱 후처리 텍스트 정규화 helper (issue #2336).

``_is_numeric_only_page_chunk`` / ``_demote_over_promoted_bullet_headings`` 은
문서 파싱 출력의 노이즈를 정규화하는 import-safe leaf(torch/chromadb/rag_core
미로드)인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- numeric: separator(공백·하이픈·점·middot·bullet·언더스코어) 제거 후 전부 digit → True.
- demote: ``_MIN_RUN_LENGTH_FOR_DEMOTION``(=3) 이상 연속 bullet heading run 만
  ``#+`` 를 떼어 평문 강등(bullet glyph 는 보존).
"""
from __future__ import annotations

from ingestion import (
    _demote_over_promoted_bullet_headings,
    _is_numeric_only_page_chunk,
)


# ---- _is_numeric_only_page_chunk ----

def test_numeric_only_true_after_stripping_separators() -> None:
    # 공백/하이픈/점/middot/bullet/언더스코어 제거 후 전부 digit → True.
    assert _is_numeric_only_page_chunk("12") is True
    assert _is_numeric_only_page_chunk("- 3 -") is True  # 하이픈·공백 strip → "3"
    assert _is_numeric_only_page_chunk("1.2.3") is True  # 점 strip → "123"
    assert _is_numeric_only_page_chunk("·• 5 _") is True  # middot·bullet·_ strip → "5"


def test_numeric_only_false_when_letters_or_empty() -> None:
    # 영문이 남으면 False(separator class 가 글자를 안 지움 → isdigit KILL).
    assert _is_numeric_only_page_chunk("page 12") is False
    assert _is_numeric_only_page_chunk("12a") is False
    # separator 제거 후 빈 문자열 → False("".isdigit() == False).
    assert _is_numeric_only_page_chunk("") is False
    assert _is_numeric_only_page_chunk("  ") is False


# ---- _demote_over_promoted_bullet_headings ----

def test_demote_strips_hash_prefix_on_run_of_three() -> None:
    # 3개 연속 bullet heading run → #+ 제거, bullet glyph('-')·빈 줄은 보존.
    src = "# - 가\n\n# - 나\n\n# - 다"
    assert _demote_over_promoted_bullet_headings(src) == "- 가\n\n- 나\n\n- 다"


def test_demote_leaves_short_run_below_threshold() -> None:
    # 2개(threshold 3 미만) run 은 무변경 — threshold 를 낮추면 강등돼 KILL.
    src = "# - 가\n\n# - 나"
    assert _demote_over_promoted_bullet_headings(src) == src


def test_demote_body_content_breaks_run() -> None:
    # 본문 줄이 run 을 끊어 각 조각이 3 미만 → 무변경(본문을 run 에 포함시키면 KILL).
    src = "# - 가\n본문\n# - 나\n# - 다"
    assert _demote_over_promoted_bullet_headings(src) == src


def test_demote_is_idempotent_and_noop_without_bullets() -> None:
    src = "# - 가\n\n# - 나\n\n# - 다"
    once = _demote_over_promoted_bullet_headings(src)
    # 이미 강등된 markdown 재실행은 no-op.
    assert _demote_over_promoted_bullet_headings(once) == once
    # bullet heading 이 아닌 일반 heading 은 run 이 아니므로 그대로.
    plain = "# 제목\n본문\n## 소제목"
    assert _demote_over_promoted_bullet_headings(plain) == plain


def test_demote_preserves_run_of_plain_non_bullet_headings() -> None:
    # bullet glyph 가 없는 일반 heading 3-run(빈 줄로만 구분) 은 강등 금지 —
    # run-length 만이 아니라 _BULLET_HEADING_RE 의 glyph 요구 자체를 pin 한다.
    # glyph class 를 '.'(아무 문자) 또는 optional 로 바꾸면 'A 사업 개요…' 로
    # 잘못 강등돼 KILL. ('A' 는 bullet glyph class 에 없으므로 run 이 아님)
    src = "# A 사업 개요\n\n# B 입찰 일정\n\n# C 평가 기준"
    assert _demote_over_promoted_bullet_headings(src) == src
