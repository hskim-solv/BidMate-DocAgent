"""Regression guard for the local ADR decision map renderer."""
from __future__ import annotations

from pathlib import Path

from scripts.render_adr_decision_map import build_board, main, parse_adr_index, render_html


ADR_README = """# ADRs

## Index

| # | Status | Title |
|---|---|---|
| [0001](./0001-preserve-naive-baseline.md) | accepted | agentic baseline |
| [0005](./0005-eval-split-public-synthetic-private-local.md) | accepted | Eval split |
| [0059](./0059-failure-mode-classifier-as-measurement-surface.md) | superseded | failure classifier |
| [0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md) | proposed | retrieval aggregate |
| [0078](./0078-pymupdf4llm-canonical-page-citation.md) | accepted | HWP/PDF citation |
"""


def test_parse_adr_index_reads_canonical_rows() -> None:
    entries = parse_adr_index(ADR_README)

    assert [entry.number for entry in entries] == [1, 5, 59, 69, 78]
    assert entries[1].area == "eval / measurement"
    assert entries[3].status == "proposed"
    assert entries[4].area == "ingestion"


def test_build_board_counts_status_and_recent() -> None:
    board = build_board(parse_adr_index(ADR_README))

    assert board["total"] == 5
    assert board["latest"] == 78
    assert board["status_counts"]["accepted"] == 3
    assert board["status_counts"]["proposed"] == 1
    assert board["status_counts"]["superseded"] == 1
    assert board["proposed"][0].number == 69


def test_html_has_sections_and_escapes_title() -> None:
    entries = parse_adr_index(
        ADR_README
        + "| [0099](./0099-x.md) | proposed | <script>alert(1)</script> |\n"
    )
    html = render_html(build_board(entries))

    assert "<!doctype html>" in html
    assert "ADR Decision Map" in html
    assert "Status Mix" in html
    assert "Decision Areas" in html
    assert "Recent ADRs" in html
    assert "Open Proposed Decisions" in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_cli_writes_html(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    out = tmp_path / "adr.html"
    readme.write_text(ADR_README, encoding="utf-8")

    rc = main(["--adr-readme", str(readme), "--out-html", str(out)])

    assert rc == 0
    assert out.exists()
    assert "ADR Decision Map" in out.read_text(encoding="utf-8")
