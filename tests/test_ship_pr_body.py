"""Tests for scripts/claude-hooks/_ship_pr_body.py.

Focuses on the build_body section shape and the test_summary path
threading. The §5b real-data-delta cascade and its round-trip
validation were removed when the §5b gate was deprecated (ADR 0084).
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
sys.path.insert(0, str(ROOT_DIR / "scripts" / "claude-hooks"))

import _ship_pr_body as pb  # noqa: E402


# ---- end-to-end build_body shape ----

def test_build_body_includes_required_sections(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["README.md"])
    monkeypatch.setattr(pb, "commit_subject", lambda base: "docs: tweak readme (#999)")
    monkeypatch.setattr(pb, "commit_body", lambda base: "Tweak README.")
    monkeypatch.setattr(pb, "has_schema_version_change", lambda base: False)
    monkeypatch.setattr(pb, "test_summary", lambda path=None: "Local tests passed.")
    body = pb.build_body("docs/issue-999-readme", "origin/main")
    for section in (
        "## 1. What changed and why",
        "Closes #999",
        "## 2. Files affected",
        "## 3. Risks",
        "## 4. Tests",
        "## 5. Eval impact",
        "## 6. Backward compatibility",
        "## 7. Out of scope",
    ):
        assert section in body, f"missing section: {section}"
    # ADR 0084: the §5b section must NOT be emitted any more.
    assert "### 5b. Real-data delta" not in body


def test_build_body_load_bearing_marks_file_and_omits_5b(monkeypatch):
    monkeypatch.setattr(pb, "changed_files", lambda base: ["rag_core.py"])
    monkeypatch.setattr(pb, "commit_subject", lambda base: "feat: foo (#238)")
    monkeypatch.setattr(pb, "commit_body", lambda base: "")
    monkeypatch.setattr(pb, "has_schema_version_change", lambda base: False)
    monkeypatch.setattr(pb, "test_summary", lambda path=None: "Local tests passed.")
    body = pb.build_body("feat/issue-238-foo", "origin/main")
    assert "(load-bearing)" in body
    # The eval-impact line notes real-data impact as a recommendation,
    # not a gated §5b section (ADR 0084).
    assert "### 5b. Real-data delta" not in body
    assert "real-data impact" in body


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
