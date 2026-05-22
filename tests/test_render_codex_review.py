"""Unit tests for scripts/render_codex_review.py — fixture-driven, no Codex network."""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts import render_codex_review as r

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "codex_review"


@pytest.fixture
def approve_payload() -> dict:
    return json.loads((FIXTURES / "approve.json").read_text(encoding="utf-8"))


@pytest.fixture
def needs_attention_payload() -> dict:
    return json.loads((FIXTURES / "needs_attention.json").read_text(encoding="utf-8"))


@pytest.fixture
def parse_error_payload() -> dict:
    return json.loads((FIXTURES / "parse_error.json").read_text(encoding="utf-8"))


@pytest.fixture
def hallucinated_payload() -> dict:
    return json.loads((FIXTURES / "hallucinated_file.json").read_text(encoding="utf-8"))


def _render(payload, rc=0, repo="hskim-solv/BidMate-DocAgent", sha="deadbeef", changed=None, stderr_tail=""):
    return r.render_markdown(
        payload=payload,
        rc=rc,
        repo=repo,
        sha=sha,
        changed=changed or set(),
        stderr_tail=stderr_tail,
    )


# ----- markdown rendering ---------------------------------------------------


def test_approve_renders_no_findings_section(approve_payload):
    md = _render(approve_payload)
    assert "`approve`" in md
    assert "No findings raised" in md
    assert "Next steps" in md
    assert "smoke" in md.lower()


def test_needs_attention_lists_findings_severity_sorted(needs_attention_payload):
    md = _render(needs_attention_payload)
    assert "`needs-attention`" in md
    # high finding should appear before medium finding
    high_idx = md.index("partial_topic_grounding")
    medium_idx = md.index("LLM judge")
    assert high_idx < medium_idx, "findings must be sorted by severity (high before medium)"


def test_findings_link_to_github_blob(needs_attention_payload):
    md = _render(needs_attention_payload)
    expected = (
        "https://github.com/hskim-solv/BidMate-DocAgent/blob/deadbeef/"
        "rag_core.py#L930-L970"
    )
    assert expected in md


def test_parse_error_surfaces_raw_output(parse_error_payload):
    md = _render(parse_error_payload)
    assert "malformed output" in md.lower()
    assert parse_error_payload["rawOutput"] in md


def test_rc_failure_renders_failure_block():
    md = _render(payload=None, rc=42, stderr_tail="ChatGPT login expired")
    assert "execution failed" in md.lower()
    assert "rc=42" in md
    assert "ChatGPT login expired" in md


def test_hallucination_marker_when_file_not_in_diff(hallucinated_payload):
    md = _render(hallucinated_payload, changed={"rag_core.py"})
    # rag_phantom_module.py is not in changed set → warning sticker
    assert "possible hallucination" in md
    # rag_core.py IS in changed → no warning on its finding line
    # heuristic: count of warning markers equals 1
    assert md.count("possible hallucination") == 1


def test_hallucination_marker_skipped_when_no_changed_set(hallucinated_payload):
    md = _render(hallucinated_payload, changed=set())
    assert "possible hallucination" not in md


def test_blob_link_falls_back_to_code_when_repo_missing(needs_attention_payload):
    md = _render(needs_attention_payload, repo=None, sha=None)
    assert "https://github.com" not in md
    assert "`rag_core.py:930-970`" in md


# ----- check summary --------------------------------------------------------


def test_check_summary_counts_severities(needs_attention_payload):
    s = r.render_check_summary(needs_attention_payload, rc=0, changed=set())
    assert "needs-attention" in s
    assert "1 high" in s
    assert "1 medium" in s


def test_check_summary_failure_path():
    s = r.render_check_summary(payload=None, rc=1, changed=set())
    assert "rc=1" in s


def test_check_summary_flags_hallucinations(hallucinated_payload):
    s = r.render_check_summary(hallucinated_payload, rc=0, changed={"rag_core.py"})
    assert "hallucination" in s
    assert "1 finding(s)" in s


def test_check_summary_no_hallucination_flag_when_no_changed_set(hallucinated_payload):
    s = r.render_check_summary(hallucinated_payload, rc=0, changed=set())
    assert "hallucination" not in s


# ----- conclusion -----------------------------------------------------------


def test_conclusion_approve_is_success(approve_payload):
    assert r.pick_conclusion(approve_payload, rc=0) == "success"


def test_conclusion_needs_attention_is_neutral(needs_attention_payload):
    assert r.pick_conclusion(needs_attention_payload, rc=0) == "neutral"


def test_conclusion_parse_error_is_neutral(parse_error_payload):
    assert r.pick_conclusion(parse_error_payload, rc=0) == "neutral"


def test_conclusion_rc_nonzero_is_neutral():
    assert r.pick_conclusion(payload=None, rc=1) == "neutral"


def test_conclusion_never_failure(needs_attention_payload, parse_error_payload):
    """Workflow invariant: this surface never blocks merge — fail is not a possible verdict."""
    for payload, rc in [
        (None, 1),
        (parse_error_payload, 0),
        (needs_attention_payload, 0),
    ]:
        assert r.pick_conclusion(payload, rc) != "failure"


# ----- comment body wrapper -------------------------------------------------


def test_comment_body_starts_with_marker(approve_payload):
    md = _render(approve_payload)
    body = r.build_comment_body(md)
    assert body.startswith(r.COMMENT_MARKER)


# ----- CLI smoke -------------------------------------------------------------


def test_cli_writes_three_artifacts(tmp_path, needs_attention_payload):
    inp = tmp_path / "codex.json"
    inp.write_text(json.dumps(needs_attention_payload), encoding="utf-8")
    out = tmp_path / "comment.md"
    sumf = tmp_path / "check_summary.md"
    concf = tmp_path / "check_conclusion.txt"
    changed = tmp_path / "files.txt"
    changed.write_text("rag_core.py\neval/judges/llm_judge.py\n", encoding="utf-8")

    rc = r.main(
        [
            "--input", str(inp),
            "--rc", "0",
            "--repo", "hskim-solv/BidMate-DocAgent",
            "--sha", "abcdef",
            "--changed-files", str(changed),
            "--output", str(out),
            "--check-summary", str(sumf),
            "--check-conclusion", str(concf),
        ]
    )
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith(r.COMMENT_MARKER)
    assert "needs-attention" in sumf.read_text(encoding="utf-8")
    assert concf.read_text(encoding="utf-8") == "neutral"
