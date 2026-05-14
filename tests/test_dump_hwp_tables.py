"""Unit tests for scripts/dump_hwp_tables.py (issue #728, PR-A0).

These tests:

* Verify the dumper's record shape validates against the published JSON
  Schema at ``eval/data/table_extraction_golden.schema.json``.
* Confirm graceful skip when pyhwp is unavailable (CI minimal install
  safe, per ADR 0036).
* Confirm the dumper writes one JSONL line per non-empty table when
  pyhwp is present (verified via a monkey-patched ``ingestion`` module
  so the test does not require a real HWP fixture).

The tests never import pyhwp directly — they only check the dumper's
behavior at the boundary it exposes.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import dump_hwp_tables as dumper  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "eval" / "data" / "table_extraction_golden.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _sample_table(table_index: int = 0) -> dict[str, Any]:
    return {
        "table_index": table_index,
        "rows": 2,
        "cols": 2,
        "cells": [
            {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "항목"},
            {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "배점"},
            {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": "기술"},
            {"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "text": "60"},
        ],
    }


def test_dump_record_shape_validates_against_schema(schema: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    record = dumper.dump_record(
        doc_id="sample",
        source_path=Path("/tmp/sample.hwp"),
        table=_sample_table(table_index=3),
        now_iso="2026-05-14T00:00:00+00:00",
    )
    assert record["doc_id"] == "sample"
    assert record["table_index"] == 3
    assert record["table_kind"] is None
    assert record["caption"] is None
    assert record["notes"] is None
    assert record["cells"][0]["text"] == "항목"
    assert record["extractor"] == "pyhwp_native_tables"
    jsonschema.validate(instance=record, schema=schema)


def test_has_nonempty_cells_filters_whitespace_only() -> None:
    empty = {
        "table_index": 0,
        "rows": 1,
        "cols": 1,
        "cells": [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "  "}],
    }
    assert not dumper._has_nonempty_cells(empty)
    assert dumper._has_nonempty_cells(_sample_table())


def test_dump_directory_skipped_when_pyhwp_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dumper, "_pyhwp_available", lambda: False)
    out = tmp_path / "out.jsonl"
    summary = dumper.dump_directory(tmp_path, out)
    assert summary["status"] == "skipped"
    assert summary["reason"] == dumper.SKIP_REASON_PYHWP_MISSING
    assert summary["tables_dumped"] == 0
    assert not out.exists()


def test_dump_directory_writes_jsonl_when_pyhwp_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema: dict[str, Any],
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    monkeypatch.setattr(dumper, "_pyhwp_available", lambda: True)

    # A dummy file on disk so ``iter_hwp_files`` returns one path; the
    # contents do not matter because the extractor is monkey-patched.
    fake_hwp = tmp_path / "fake.hwp"
    fake_hwp.write_bytes(b"\x00")

    def fake_extract(source_path: Path):
        return None, [_sample_table(table_index=0), _sample_table(table_index=1)]

    fake_module = types.ModuleType("ingestion")
    fake_module._extract_hwp_native_with_tables = fake_extract  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ingestion", fake_module)

    out = tmp_path / "draft.jsonl"
    summary = dumper.dump_directory(tmp_path, out)
    assert summary["status"] == "ok"
    assert summary["files_seen"] == 1
    assert summary["tables_dumped"] == 2
    assert summary["failures"] == []

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        jsonschema.validate(instance=record, schema=schema)
        assert record["doc_id"] == "fake"
        assert record["table_kind"] is None


def test_dump_directory_isolates_per_file_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dumper, "_pyhwp_available", lambda: True)

    (tmp_path / "good.hwp").write_bytes(b"\x00")
    (tmp_path / "bad.hwp").write_bytes(b"\x00")

    def fake_extract(source_path: Path):
        if source_path.name == "bad.hwp":
            raise RuntimeError("simulated pyhwp parse failure")
        return None, [_sample_table(table_index=0)]

    fake_module = types.ModuleType("ingestion")
    fake_module._extract_hwp_native_with_tables = fake_extract  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ingestion", fake_module)

    out = tmp_path / "draft.jsonl"
    summary = dumper.dump_directory(tmp_path, out)
    assert summary["status"] == "ok"
    assert summary["files_seen"] == 2
    assert summary["tables_dumped"] == 1
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["file"] == "bad.hwp"
    assert "simulated pyhwp parse failure" in summary["failures"][0]["error"]


def test_dump_directory_skips_empty_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dumper, "_pyhwp_available", lambda: True)

    (tmp_path / "fake.hwp").write_bytes(b"\x00")

    def fake_extract(source_path: Path):
        empty = {
            "table_index": 0,
            "rows": 1,
            "cols": 1,
            "cells": [
                {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "   "},
            ],
        }
        return None, [empty, _sample_table(table_index=1)]

    fake_module = types.ModuleType("ingestion")
    fake_module._extract_hwp_native_with_tables = fake_extract  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ingestion", fake_module)

    out = tmp_path / "draft.jsonl"
    summary = dumper.dump_directory(tmp_path, out)
    assert summary["tables_dumped"] == 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["table_index"] == 1


def test_cli_returns_2_when_hwp_dir_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "nope"
    rc = dumper.main(["--hwp-dir", str(missing), "--out", str(tmp_path / "out.jsonl")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "does not exist" in captured.err
