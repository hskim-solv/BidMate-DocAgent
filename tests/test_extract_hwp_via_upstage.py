"""Unit tests for scripts/extract_hwp_via_upstage.py (issue #773, PR-A1).

These tests:

* Verify the HTML→cells parser correctly handles rowspan / colspan via
  the internal occupancy grid (the trickiest piece of the dumper).
* Verify both Upstage response shape variants (``elements[*].html`` and
  ``elements[*].content.html``) are tolerated.
* Verify the dumper's record shape validates against the published JSON
  Schema at ``eval/data/table_extraction_golden.schema.json`` (same
  schema as PR-A0).
* Confirm graceful skip when ``UPSTAGE_API_KEY`` is unset.
* Confirm per-file failures are isolated (network exception on one file
  must not stop the others).

The tests never call the real Upstage endpoint — a mock
``requests.Session`` is injected so CI runs without secrets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import extract_hwp_via_upstage as extractor  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "eval" / "data" / "table_extraction_golden.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- parse_table_html --------------------------------------------------


def test_parse_table_html_simple_grid() -> None:
    html = """
    <table>
      <tr><th>항목</th><th>배점</th></tr>
      <tr><td>기술</td><td>60</td></tr>
      <tr><td>가격</td><td>40</td></tr>
    </table>
    """
    rows, cols, cells = extractor.parse_table_html(html)
    assert rows == 3
    assert cols == 2
    assert len(cells) == 6
    assert cells[0] == {
        "row": 0,
        "col": 0,
        "rowspan": 1,
        "colspan": 1,
        "text": "항목",
    }
    assert cells[-1]["text"] == "40"


def test_parse_table_html_rowspan_skips_occupied_column() -> None:
    # First col spans 2 rows. The second cell on row 1 must land at col 1.
    html = """
    <table>
      <tr><td rowspan="2">A</td><td>B</td></tr>
      <tr><td>C</td></tr>
    </table>
    """
    rows, cols, cells = extractor.parse_table_html(html)
    assert rows == 2
    assert cols == 2
    coord = {(c["row"], c["col"]): c["text"] for c in cells}
    assert coord[(0, 0)] == "A"
    assert coord[(0, 1)] == "B"
    assert coord[(1, 1)] == "C"
    # Cell "A" should still report rowspan=2.
    a_cell = next(c for c in cells if c["text"] == "A")
    assert a_cell["rowspan"] == 2


def test_parse_table_html_colspan_advances_col_idx() -> None:
    html = """
    <table>
      <tr><td colspan="2">header</td></tr>
      <tr><td>left</td><td>right</td></tr>
    </table>
    """
    rows, cols, cells = extractor.parse_table_html(html)
    assert rows == 2
    assert cols == 2
    header = next(c for c in cells if c["text"] == "header")
    assert header["colspan"] == 2
    assert header["col"] == 0


# --- extract_tables_from_response --------------------------------------


def test_extract_tables_from_response_tolerates_top_level_html() -> None:
    response = {
        "elements": [
            {"category": "paragraph", "html": "<p>intro</p>"},
            {
                "category": "table",
                "id": 0,
                "page": 3,
                "html": "<table><tr><td>x</td></tr></table>",
            },
        ]
    }
    tables = extractor.extract_tables_from_response(response)
    assert len(tables) == 1
    assert tables[0]["table_index"] == 0
    assert tables[0]["page"] == 3
    assert tables[0]["cells"][0]["text"] == "x"


def test_extract_tables_from_response_tolerates_nested_content_html() -> None:
    response = {
        "elements": [
            {
                "category": "table",
                "content": {"html": "<table><tr><td>y</td></tr></table>"},
            }
        ]
    }
    tables = extractor.extract_tables_from_response(response)
    assert len(tables) == 1
    assert tables[0]["cells"][0]["text"] == "y"


def test_extract_tables_from_response_skips_non_table_categories() -> None:
    response = {
        "elements": [
            {"category": "paragraph", "html": "<p>nope</p>"},
            {"category": "figure", "html": "<img/>"},
        ]
    }
    assert extractor.extract_tables_from_response(response) == []


def test_extract_tables_from_response_skips_empty_or_missing_html() -> None:
    response = {
        "elements": [
            {"category": "table", "html": ""},
            {"category": "table"},
            {"category": "table", "content": {}},
        ]
    }
    assert extractor.extract_tables_from_response(response) == []


# --- dump_record / schema validation -----------------------------------


def test_dump_record_validates_against_schema(schema: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    table = {
        "table_index": 2,
        "rows": 2,
        "cols": 2,
        "page": 5,
        "cells": [
            {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "항목"},
            {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "배점"},
        ],
    }
    record = extractor.dump_record(
        doc_id="sample",
        source_path=Path("/tmp/sample.hwp"),
        table=table,
        now_iso="2026-05-14T00:00:00+00:00",
    )
    assert record["doc_id"] == "sample"
    assert record["table_index"] == 2
    assert record["page"] == 5
    assert record["extractor"] == "upstage_document_parser"
    assert record["table_kind"] is None
    assert record["caption"] is None
    assert record["notes"] is None
    jsonschema.validate(instance=record, schema=schema)


# --- extract_directory: skip / write / failure isolation ---------------


def test_extract_directory_skipped_when_api_key_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    out = tmp_path / "out.jsonl"
    summary = extractor.extract_directory(tmp_path, out)
    assert summary["status"] == "skipped"
    assert summary["reason"] == extractor.SKIP_REASON_KEY_MISSING
    assert summary["tables_dumped"] == 0
    assert not out.exists()


def _mock_session_returning(response_body: dict[str, Any]) -> MagicMock:
    session = MagicMock()
    fake_response = MagicMock()
    fake_response.json.return_value = response_body
    fake_response.raise_for_status.return_value = None
    session.post.return_value = fake_response
    return session


def test_extract_directory_writes_jsonl_when_key_present(
    tmp_path: Path,
    schema: dict[str, Any],
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    (tmp_path / "fake.hwp").write_bytes(b"\x00")

    response = {
        "elements": [
            {
                "category": "table",
                "page": 1,
                "html": "<table><tr><td>a</td><td>b</td></tr></table>",
            },
            {
                "category": "table",
                "page": 2,
                "html": "<table><tr><td>c</td></tr></table>",
            },
        ]
    }
    session = _mock_session_returning(response)
    out = tmp_path / "draft.jsonl"
    summary = extractor.extract_directory(
        tmp_path,
        out,
        api_key="fake-key",
        session=session,
    )
    assert summary["status"] == "ok"
    assert summary["files_seen"] == 1
    assert summary["tables_dumped"] == 2
    assert summary["failures"] == []
    assert session.post.call_count == 1

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        jsonschema.validate(instance=record, schema=schema)
        assert record["doc_id"] == "fake"
        assert record["extractor"] == "upstage_document_parser"


def test_extract_directory_isolates_per_file_failures(tmp_path: Path) -> None:
    (tmp_path / "good.hwp").write_bytes(b"\x00")
    (tmp_path / "bad.hwp").write_bytes(b"\x00")

    session = MagicMock()

    def fake_post(*args, **kwargs):
        # Inspect which file is being posted by reading the in-memory
        # ``files`` tuple. The filename is the first element.
        files = kwargs.get("files") or {}
        document = files.get("document")
        name = document[0] if isinstance(document, tuple) else "?"
        if name == "bad.hwp":
            raise RuntimeError("simulated upstream failure")
        resp = MagicMock()
        resp.json.return_value = {
            "elements": [
                {
                    "category": "table",
                    "html": "<table><tr><td>ok</td></tr></table>",
                }
            ]
        }
        resp.raise_for_status.return_value = None
        return resp

    session.post.side_effect = fake_post

    out = tmp_path / "draft.jsonl"
    summary = extractor.extract_directory(
        tmp_path,
        out,
        api_key="fake-key",
        session=session,
    )
    assert summary["status"] == "ok"
    assert summary["files_seen"] == 2
    assert summary["tables_dumped"] == 1
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["file"] == "bad.hwp"
    assert "simulated upstream failure" in summary["failures"][0]["error"]


def test_extract_directory_skips_tables_with_only_whitespace_cells(
    tmp_path: Path,
) -> None:
    (tmp_path / "fake.hwp").write_bytes(b"\x00")
    response = {
        "elements": [
            {"category": "table", "html": "<table><tr><td>   </td></tr></table>"},
            {"category": "table", "html": "<table><tr><td>real</td></tr></table>"},
        ]
    }
    session = _mock_session_returning(response)
    out = tmp_path / "draft.jsonl"
    summary = extractor.extract_directory(
        tmp_path,
        out,
        api_key="fake-key",
        session=session,
    )
    assert summary["tables_dumped"] == 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["cells"][0]["text"] == "real"


def test_cli_returns_2_when_hwp_dir_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "nope"
    rc = extractor.main(["--hwp-dir", str(missing), "--out", str(tmp_path / "out.jsonl")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_cli_skips_with_message_when_api_key_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    rc = extractor.main(["--hwp-dir", str(tmp_path), "--out", str(tmp_path / "out.jsonl")])
    assert rc == 0
    captured = capsys.readouterr()
    assert "UPSTAGE_API_KEY not set" in captured.err
