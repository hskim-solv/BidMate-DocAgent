"""Unit coverage for ``scripts/check_doc_links.py::_iter_heading_lines``.

`check_doc_links.py` 는 cross-reference 무결성 SSoT 다. `_iter_heading_lines` 는
markdown 에서 **GitHub anchor 가 생기는** ATX heading 라인만 추출한다 — leading
YAML front-matter, fenced code block(```/~~~), HTML comment block 을 skip 하고
``# ``(해시+공백) 1~6레벨만 인정한다. 이 skip-region 로직이 조용히 회귀하면
fragment-link 검사가 가짜 anchor 를 만들거나 실제 heading 을 놓친다.

모든 기대값은 pristine 소스 실행으로 캡처했다. ``check_doc_links`` 가 모듈 내부에서
``from _governance import ...`` (top-level) 를 하므로 import 전에 ``scripts/`` 를
``sys.path`` 에 넣는다(기존 ``tests/test_doc_links.py`` 와 동일 런타임 요건). 단
정적 분석이 해결할 수 있도록 ``from scripts.check_doc_links import`` 형태로 임포트한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from scripts.check_doc_links import _iter_heading_lines  # noqa: E402


def _headings(text: str) -> list[str]:
    return list(_iter_heading_lines(text))


def test_basic_atx_headings_yielded() -> None:
    assert _headings("# A\ntext\n## B\n") == ["# A", "## B"]


def test_empty_text_yields_nothing() -> None:
    assert _headings("") == []


# ----------------------------------------------------------------------
# leading YAML front-matter
# ----------------------------------------------------------------------


def test_leading_frontmatter_body_is_skipped() -> None:
    # 첫 줄이 정확히 `---` 일 때만 front-matter; body 안의 heading-shaped 줄까지
    # skip 하고 닫는 `---` 이후 heading 만 yield (body skip 을 명시적으로 핀).
    text = "---\ntitle: x\n# Fake In Frontmatter\n---\n# Real\n"
    assert _headings(text) == ["# Real"]


def test_dashdash_first_line_is_not_frontmatter() -> None:
    # 첫 줄이 `--`(정확히 `---` 아님)면 front-matter opener 가 아니다 — 이후 heading 유지.
    assert _headings("--\n# H\n") == ["# H"]


def test_midfile_triple_dash_is_not_frontmatter() -> None:
    # 첫 줄이 아니면 `---` 는 front-matter 가 아니라 thematic break — 이후 heading 유지.
    text = "text\n---\n# Still A Heading\n"
    assert _headings(text) == ["# Still A Heading"]


# ----------------------------------------------------------------------
# fenced code blocks
# ----------------------------------------------------------------------


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_code_block_headings_skipped(fence: str) -> None:
    # 펜스(backtick/tilde) 내부의 `#` 라인은 heading 이 아니다.
    text = f"# Keep\n{fence}\n# In Fence\n{fence}\n# After\n"
    assert _headings(text) == ["# Keep", "# After"]


# ----------------------------------------------------------------------
# HTML comment blocks
# ----------------------------------------------------------------------


def test_html_comment_block_headings_skipped() -> None:
    text = "# Keep\n<!--\n# In Comment\n-->\n# After\n"
    assert _headings(text) == ["# Keep", "# After"]


def test_single_line_html_comment_heading_skipped() -> None:
    text = "# Keep\n<!-- # In Comment -->\n# After\n"
    assert _headings(text) == ["# Keep", "# After"]


# ----------------------------------------------------------------------
# ATX 인정 경계
# ----------------------------------------------------------------------


def test_hash_without_space_is_not_heading() -> None:
    # `#NoSpace`/`#` 단독은 ATX heading 아님 — `# `(해시+공백)만 인정.
    assert _headings("#NoSpace maybe\n#\n# Real\n") == ["# Real"]


def test_atx_levels_one_through_six_only() -> None:
    # 1~6 해시만; 7 해시는 ATX 범위 밖이라 제외.
    assert _headings("# h1\n###### h6\n####### h7too\n") == ["# h1", "###### h6"]


def test_indented_heading_is_yielded() -> None:
    # 4칸 미만 들여쓰기는 코드블록이 아니므로 heading 으로 인정(선행 공백 보존).
    assert _headings("  # Indented\n# Top\n") == ["  # Indented", "# Top"]
