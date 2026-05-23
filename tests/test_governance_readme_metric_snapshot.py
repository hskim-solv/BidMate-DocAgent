"""README metric-row ↔ committed-snapshot parity (issue #792).

The README metric table (between the ``METRICS_TABLE`` markers) is generated
from a public-synthetic eval. ``reports/eval_summary.snapshot.json`` is the
committed source of truth for those numbers; the CI gate
(``update_readme_metrics.py --check``) verifies the README's metric *rows*
match what the renderer produces from that snapshot — it does NOT re-measure
(the #739/#751 source-mismatch failure).

The block's ``<details>``/``<summary>`` + caption are hand-curated Korean prose
(Koreanized in PR #1116) that the renderer does not own, so the gate is scoped
to the ``|``-delimited rows via ``splice_table_rows`` (prose preserved in
place). These tests pin that splice behavior + a real-repo sentinel so README
number drift cannot merge silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.update_readme_metrics import (
    END_MARKER,
    START_MARKER,
    _table_rows,
    render_table,
    splice_table_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "reports" / "eval_summary.snapshot.json"
README = REPO_ROOT / "README.md"


# ---- splice_table_rows ----------------------------------------------------


def _block(rows_and_prose: str) -> str:
    return f"intro\n{START_MARKER}\n{rows_and_prose}\n{END_MARKER}\ntrailer\n"


def test_splice_replaces_rows_preserves_prose() -> None:
    readme = _block(
        "| A | B |\n|---|---|\n| 1 | old |\n"
        "<details><summary>한국어 prose</summary>\n"
        "| C | D |\n| 2 | old |\n"
        "</details>\n> 캡션 prose"
    )
    new_table = "| A | B |\n|---|---|\n| 1 | NEW |\n| C | D |\n| 2 | NEW |"
    out, match = splice_table_rows(readme, new_table)
    assert match is True
    # Numeric rows replaced …
    assert "| 1 | NEW |" in out and "| 2 | NEW |" in out
    assert "old" not in out
    # … prose untouched.
    assert "<details><summary>한국어 prose</summary>" in out
    assert "> 캡션 prose" in out
    # Outside-block text untouched.
    assert out.startswith("intro\n") and out.endswith("trailer\n")


def test_splice_only_touches_inside_marker_rows() -> None:
    # A pipe row OUTSIDE the markers must not be consumed.
    readme = f"| outside | row |\n{START_MARKER}\n| in | row |\n{END_MARKER}\n"
    new_table = "| in | CHANGED |"
    out, match = splice_table_rows(readme, new_table)
    assert match is True
    assert "| outside | row |" in out
    assert "| in | CHANGED |" in out


def test_splice_structural_mismatch_when_row_count_differs() -> None:
    readme = _block("| A | B |\n| 1 | x |")
    # Renderer produces an extra row → structural mismatch (run added/removed).
    new_table = "| A | B |\n| 1 | x |\n| 2 | y |"
    _out, match = splice_table_rows(readme, new_table)
    assert match is False


def test_splice_idempotent_when_rows_already_match() -> None:
    body = "| A | B |\n|---|---|\n| 1 | x |\n<summary>prose</summary>"
    readme = _block(body)
    new_table = "| A | B |\n|---|---|\n| 1 | x |"
    out, match = splice_table_rows(readme, new_table)
    assert match is True
    assert out == readme


# ---- real-repo sentinel ---------------------------------------------------


def test_snapshot_file_is_committed() -> None:
    assert SNAPSHOT.exists(), (
        "reports/eval_summary.snapshot.json is missing — it is the committed "
        "source of truth for README metrics (issue #792). Run `make snapshot-update`."
    )
    json.loads(SNAPSHOT.read_text(encoding="utf-8"))  # must be valid JSON


def test_repo_readme_rows_match_snapshot() -> None:
    """Always-on gate: the live README metric rows equal what the renderer
    produces from the committed snapshot. When a metric moves and the snapshot
    is not refreshed (or vice versa), this fails fast (CI red) so the drift
    cannot merge silently. Regenerate with `make snapshot-update`.
    """
    summary = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    readme_text = README.read_text(encoding="utf-8")
    _spliced, structural_match = splice_table_rows(readme_text, render_table(summary))
    assert structural_match, (
        "README metric-row count differs from the snapshot — a run was "
        "added/removed. Run `make snapshot-update`."
    )

    start = readme_text.find(START_MARKER)
    end = readme_text.find(END_MARKER)
    block = readme_text[start:end]
    readme_rows = _table_rows(block)
    rendered_rows = _table_rows(render_table(summary))
    assert readme_rows == rendered_rows, (
        "README metric rows drifted from reports/eval_summary.snapshot.json. "
        "Run `make snapshot-update` to resync."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
