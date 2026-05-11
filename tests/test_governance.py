"""Drift guard for the load-bearing path SSoT (`scripts/_governance.py`)
plus regex-level checks for the §5b enforcement in
`scripts/check_branch_and_issue.py`.

The same conceptual list previously lived in three places with subtle
differences. These tests ensure all three consumers reach back to the
SSoT instead of carrying their own copy. The §5b tests confirm the
gating logic accepts the documented escape sentence and rejects an
empty/comment-only template body (which would otherwise let PR #69-class
regressions through).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import _governance as gov  # noqa: E402
import check_branch_and_issue as cbi  # noqa: E402


@pytest.mark.parametrize("entry", [
    "rag_core.py",
    "ingestion.py",
    "visual_ingestion.py",
    "eval/",
    "api/",
    "docs/adr/",
])
def test_canonical_list_contains_claude_md_entries(entry):
    assert entry in gov.LOAD_BEARING_PATHS, (
        f"CLAUDE.md lists {entry!r} as load-bearing but the SSoT does not."
    )


@pytest.mark.parametrize("path", [
    "rag_core.py",
    "./rag_core.py",
    "ingestion.py",
    "visual_ingestion.py",
    "eval/config.yaml",
    "eval/run_eval.py",
    "api/main.py",
    "docs/adr/0001-preserve-naive-baseline.md",
    "scripts/build_index.py",
    "/Users/x/proj/rag_core.py",
    "/abs/path/to/api/main.py",
    "/abs/path/to/docs/adr/0007.md",
])
def test_is_load_bearing_accepts(path):
    assert gov.is_load_bearing(path), f"expected load-bearing: {path!r}"


@pytest.mark.parametrize("path", [
    "",
    "README.md",
    "CHANGELOG.md",
    "myapi/main.py",
    "preeval/foo.py",
    "tests/test_governance.py",
    "scripts/check_branch_and_issue.py",
    "data/raw/example.pdf",
    "rag_core_helper.py",
])
def test_is_load_bearing_rejects(path):
    assert not gov.is_load_bearing(path), f"expected NOT load-bearing: {path!r}"


def test_pre_push_hook_uses_governance_module():
    text = (ROOT_DIR / ".githooks" / "pre-push").read_text()
    assert "_governance.py" in text, (
        ".githooks/pre-push must call scripts/_governance.py (SSoT) "
        "instead of carrying its own WATCH_PATTERNS array."
    )


def test_pretooluse_hook_uses_governance_module():
    text = (
        ROOT_DIR / "scripts" / "claude-hooks" / "pretooluse-loadbearing.sh"
    ).read_text()
    assert "_governance.py" in text, (
        "PreToolUse hook must call scripts/_governance.py (SSoT) "
        "instead of carrying its own LOAD_BEARING_PATTERNS array."
    )


def test_pr_template_mentions_all_canonical_entries():
    template = (
        ROOT_DIR / ".github" / "pull_request_template.md"
    ).read_text()
    for entry in gov.LOAD_BEARING_PATHS:
        assert entry in template, (
            f"PR template must mention load-bearing entry {entry!r} "
            f"so reviewers see the §5b trigger surface. "
            f"Update .github/pull_request_template.md to keep it in sync "
            f"with scripts/_governance.LOAD_BEARING_PATHS."
        )


def test_five_b_section_absent_when_no_header():
    assert cbi._five_b_section("nothing here") is None


def test_five_b_section_found_with_default_template_only():
    body = (
        "### 5b. Real-data delta\n\n"
        "<!--\n"
        "Required if load-bearing path changed.\n"
        "Attach `make real-eval-delta` table or state:\n"
        "'No behavior change in retrieval / verifier path.'\n"
        "-->\n"
    )
    section = cbi._five_b_section(body)
    assert section is not None, "header is present, even if section is empty"
    assert not cbi.FIVE_B_TABLE_RE.search(section), (
        "comment-only template body must NOT count as a markdown table"
    )
    assert not cbi.FIVE_B_ESCAPE_RE.search(section), (
        "escape sentence inside an HTML comment must be stripped, "
        "otherwise the default empty template would silently satisfy §5b"
    )


def test_five_b_table_regex_matches_real_eval_delta_aggregate():
    section = (
        "\n\n"
        "| metric | base | head | delta |\n"
        "|---|---|---|---|\n"
        "| accuracy | 0.82 | 0.84 | +0.02 |\n"
    )
    assert cbi.FIVE_B_TABLE_RE.search(section)


@pytest.mark.parametrize("sentence", [
    "No behavior change in retrieval path.",
    "No behavior change in verifier path.",
    "No behavior change in retrieval / verifier path.",
    "no behavior change in eval path",
    "No behavior change in API path.",
    "No behavior change in ingestion path.",
])
def test_five_b_escape_regex_accepts_documented_escape(sentence):
    assert cbi.FIVE_B_ESCAPE_RE.search(sentence), (
        f"Escape sentence not recognized: {sentence!r}"
    )


@pytest.mark.parametrize("sentence", [
    "No behavior change anywhere.",
    "We changed retrieval behavior.",
    "TODO: add real-eval delta.",
])
def test_five_b_escape_regex_rejects_off_pattern(sentence):
    assert not cbi.FIVE_B_ESCAPE_RE.search(sentence), (
        f"Should not match escape: {sentence!r}"
    )
