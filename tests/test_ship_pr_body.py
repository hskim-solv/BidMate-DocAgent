"""Tests for scripts/claude-hooks/_ship_pr_body.py.

Focuses on the §5b cascade decision logic and the validate_5b
round-trip check. Subprocess-heavy paths (running real-eval) are
skipped via monkeypatch; we don't actually invoke `make real-eval`
in the test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
sys.path.insert(0, str(ROOT_DIR / "scripts" / "claude-hooks"))

import _ship_pr_body as pb  # noqa: E402


# ---- §5b cascade ----

def test_render_5b_no_load_bearing():
    out = pb.render_5b([], "auto")
    assert "no load-bearing path changed" in out
    assert "No behavior change in retrieval" in out


def test_render_5b_skip_mode():
    out = pb.render_5b(["rag_core.py"], "skip")
    assert "REAL_EVAL=skip" in out
    assert "No behavior change in retrieval" in out


def test_render_5b_load_bearing_no_data(monkeypatch):
    monkeypatch.setattr(pb, "can_run_real_eval", lambda: False)
    out = pb.render_5b(["rag_core.py"], "auto")
    assert "real-eval not runnable" in out
    assert "No behavior change in retrieval" in out


def test_render_5b_async_inserts_pending_marker(monkeypatch):
    monkeypatch.setattr(pb, "can_run_real_eval", lambda: True)
    out = pb.render_5b(["rag_core.py"], "async")
    assert "real-eval-pending" in out
    assert "No behavior change in retrieval" in out


def test_render_5b_uses_cache_when_valid(monkeypatch):
    monkeypatch.setattr(pb, "can_run_real_eval", lambda: True)
    monkeypatch.setattr(pb, "real_eval_cache_valid", lambda: True)
    monkeypatch.setattr(pb, "_run", lambda cmd, timeout=60: (
        (0, "| metric | base | head |\n|---|---|---|\n| f1 | 0.7 | 0.8 |", "")
        if cmd == ["make", "real-eval-delta"]
        else (1, "", "unexpected cmd")
    ))
    out = pb.render_5b(["rag_core.py"], "auto")
    assert "metric" in out and "f1" in out


def test_render_5b_handles_eval_failure(monkeypatch):
    monkeypatch.setattr(pb, "can_run_real_eval", lambda: True)
    monkeypatch.setattr(pb, "real_eval_cache_valid", lambda: False)
    monkeypatch.setattr(
        pb, "_run", lambda cmd, timeout=60: (1, "", "stub failure")
    )
    out = pb.render_5b(["rag_core.py"], "auto")
    assert "real-eval-failed" in out
    assert "No behavior change in retrieval" in out


# ---- validate_5b round-trip ----

def test_validate_5b_passes_with_table():
    body = (
        "## 5. Eval impact\n\n"
        "### 5b. Real-data delta\n\n"
        "| metric | base | head |\n"
        "|---|---|---|\n"
        "| f1 | 0.7 | 0.8 |\n"
        "\n## 6. Backward compatibility\n"
    )
    assert pb.validate_5b(body, ["rag_core.py"]) is True


def test_validate_5b_passes_with_escape_sentence():
    body = (
        "### 5b. Real-data delta\n\n"
        "No behavior change in retrieval / verifier path.\n"
    )
    assert pb.validate_5b(body, ["rag_core.py"]) is True


def test_validate_5b_rejects_empty_section():
    body = (
        "### 5b. Real-data delta\n\n"
        "<!-- only a comment, no actual content -->\n"
        "\n## 6. Backward compatibility\n"
    )
    assert pb.validate_5b(body, ["rag_core.py"]) is False


def test_validate_5b_rejects_missing_header():
    body = "## 5. Eval impact\n\nAll `·`.\n\n## 6. Backward compatibility\n"
    assert pb.validate_5b(body, ["rag_core.py"]) is False


def test_validate_5b_skipped_when_no_load_bearing():
    body = "anything goes when no load-bearing change"
    assert pb.validate_5b(body, []) is True


# ---- check_body_5b standalone validation (issue #1097) ----

def test_check_body_5b_no_load_bearing_passes(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["README.md", "docs/x.md"])
    assert pb.check_body_5b("anything, no 5b section here", "origin/main") == 0


def test_check_body_5b_load_bearing_with_escape_passes(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["rag_core.py"])
    body = (
        "### 5b. Real-data delta\n\n"
        "No behavior change in retrieval / verifier path.\n"
    )
    assert pb.check_body_5b(body, "origin/main") == 0


def test_check_body_5b_load_bearing_with_table_passes(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["api/main.py"])
    body = (
        "### 5b. Real-data delta\n\n"
        "| metric | base | head |\n|---|---|---|\n| f1 | 0.7 | 0.8 |\n"
        "\n## 6. Backward compatibility\n"
    )
    assert pb.check_body_5b(body, "origin/main") == 0


def test_check_body_5b_load_bearing_missing_5b_returns_3(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["rag_core.py"])
    body = "## 1. What changed\n\nsome text without any 5b section\n"
    assert pb.check_body_5b(body, "origin/main") == 3


# ---- end-to-end build_body shape ----

def test_build_body_includes_required_sections(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["README.md"])
    monkeypatch.setattr(pb, "commit_subject", lambda base: "docs: tweak readme (#999)")
    monkeypatch.setattr(pb, "commit_body", lambda base: "Tweak README.")
    monkeypatch.setattr(pb, "has_schema_version_change", lambda base: False)
    monkeypatch.setattr(pb, "test_summary", lambda path=None: "Local tests passed.")
    body = pb.build_body("docs/issue-999-readme", "origin/main", "auto")
    for section in (
        "## 1. What changed and why",
        "Closes #999",
        "## 2. Files affected",
        "## 3. Risks",
        "## 4. Tests",
        "## 5. Eval impact",
        "### 5b. Real-data delta",
        "## 6. Backward compatibility",
        "## 7. Out of scope",
    ):
        assert section in body, f"missing section: {section}"


def test_build_body_load_bearing_routes_through_5b(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["rag_core.py"])
    monkeypatch.setattr(pb, "commit_subject", lambda base: "feat: foo (#238)")
    monkeypatch.setattr(pb, "commit_body", lambda base: "")
    monkeypatch.setattr(pb, "has_schema_version_change", lambda base: False)
    monkeypatch.setattr(pb, "test_summary", lambda path=None: "Local tests passed.")
    monkeypatch.setattr(pb, "can_run_real_eval", lambda: False)
    body = pb.build_body("feat/issue-238-foo", "origin/main", "auto")
    assert "(load-bearing)" in body
    assert "See §5b" in body or "5b" in body
    assert pb.validate_5b(body, ["rag_core.py"]) is True


# ---- test_summary path threading (issue #1274) ----

def test_test_summary_reads_dispatcher_path(tmp_path):
    p = tmp_path / "summary.txt"
    p.write_text("Local tests passed (bash scripts/test.sh).")
    assert pb.test_summary(str(p)) == "Local tests passed (bash scripts/test.sh)."


def test_test_summary_none_path_not_captured():
    # No path = dispatcher did not pass one; never falls back to a global
    # /tmp file that a concurrent worktree could have left behind (#1274).
    assert pb.test_summary(None) == "Local test run not captured by dispatcher."


def test_test_summary_missing_path_not_captured(tmp_path):
    missing = tmp_path / "does-not-exist.txt"
    assert pb.test_summary(str(missing)) == "Local test run not captured by dispatcher."
