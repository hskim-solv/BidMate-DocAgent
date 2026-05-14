#!/usr/bin/env python3
"""Dump pyhwp native table extraction as draft golden JSONL (issue #728).

Walks a directory of HWP files, runs
``ingestion._extract_hwp_native_with_tables`` on each, and emits one JSONL
line per non-empty table conforming to
``eval/data/table_extraction_golden.schema.json``.

Output is a **draft**: ``table_kind``, ``caption``, and ``notes`` are left
``null`` for the human labeler to fill in. ``page`` is ``null`` because
pyhwp's event stream does not expose page mappings.

Off-pipeline measurement tool. Default HWP loader (ADR 0036) is unchanged.
Gracefully skips when pyhwp is unavailable so CI minimal installs remain
green. Per-file extraction errors are reported in the summary, never
re-raised.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


EXTRACTOR_TAG = "pyhwp_native_tables"
SKIP_REASON_PYHWP_MISSING = "pyhwp_not_installed"


def _pyhwp_available() -> bool:
    """Return True iff the optional ``hwp5`` package is importable."""
    return importlib.util.find_spec("hwp5") is not None


def _now_iso() -> str:
    """Return current UTC time in ISO-8601 (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _has_nonempty_cells(table: dict[str, Any]) -> bool:
    """True iff at least one cell has non-whitespace text."""
    for cell in table.get("cells") or []:
        if str(cell.get("text", "")).strip():
            return True
    return False


def dump_record(
    doc_id: str,
    source_path: Path,
    table: dict[str, Any],
    *,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Build one golden draft record from a pyhwp-extracted table.

    ``now_iso`` is injectable so tests can pin a deterministic timestamp.
    """
    return {
        "doc_id": doc_id,
        "source_path": str(source_path),
        "page": None,
        "table_index": int(table.get("table_index", 0) or 0),
        "rows": int(table.get("rows", 0) or 0),
        "cols": int(table.get("cols", 0) or 0),
        "caption": None,
        "table_kind": None,
        "cells": [
            {
                "row": int(cell.get("row", 0) or 0),
                "col": int(cell.get("col", 0) or 0),
                "rowspan": int(cell.get("rowspan", 1) or 1),
                "colspan": int(cell.get("colspan", 1) or 1),
                "text": str(cell.get("text", "")),
            }
            for cell in (table.get("cells") or [])
        ],
        "extractor": EXTRACTOR_TAG,
        "extracted_at": now_iso or _now_iso(),
        "notes": None,
    }


def iter_hwp_files(hwp_dir: Path) -> Iterable[Path]:
    """Yield ``.hwp`` files in ``hwp_dir`` in deterministic (sorted) order."""
    return sorted(p for p in hwp_dir.glob("*.hwp") if p.is_file())


def dump_directory(hwp_dir: Path, out_path: Path) -> dict[str, Any]:
    """Iterate ``hwp_dir`` and emit one JSONL line per non-empty table.

    Returns a summary dict for the CLI to print. Never raises on per-file
    extraction errors — each failure is reported in the summary's
    ``failures`` list instead.
    """
    if not _pyhwp_available():
        return {
            "status": "skipped",
            "reason": SKIP_REASON_PYHWP_MISSING,
            "files_seen": 0,
            "tables_dumped": 0,
            "failures": [],
        }

    # Late import: pyhwp is opt-in (ADR 0036). Importing ``ingestion`` only
    # after the availability check keeps ``--help`` working in minimal envs.
    from ingestion import _extract_hwp_native_with_tables  # type: ignore[import-not-found]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_hwp_files(hwp_dir))
    tables_dumped = 0
    failures: list[dict[str, str]] = []

    with out_path.open("w", encoding="utf-8") as fh:
        for source in files:
            try:
                _text, tables = _extract_hwp_native_with_tables(source)
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                failures.append({"file": source.name, "error": repr(exc)})
                continue
            for table in tables:
                if not _has_nonempty_cells(table):
                    continue
                record = dump_record(
                    doc_id=source.stem,
                    source_path=source,
                    table=table,
                )
                fh.write(json.dumps(record, ensure_ascii=False))
                fh.write("\n")
                tables_dumped += 1

    return {
        "status": "ok",
        "files_seen": len(files),
        "tables_dumped": tables_dumped,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dump pyhwp native table extraction as draft golden JSONL "
            "(issue #728, PR-A0 of HWP RAG table experiment). "
            "Off-pipeline measurement only; the default HWP loader is unchanged."
        )
    )
    parser.add_argument(
        "--hwp-dir",
        type=Path,
        required=True,
        help="Directory containing .hwp files (local-only; ADR 0005 boundary).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "outputs" / "table_golden_draft.jsonl",
        help=(
            "Output JSONL path "
            "(default: outputs/table_golden_draft.jsonl, gitignored)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hwp_dir = args.hwp_dir
    if not hwp_dir.exists() or not hwp_dir.is_dir():
        print(
            f"error: --hwp-dir does not exist or is not a directory: {hwp_dir}",
            file=sys.stderr,
        )
        return 2
    summary = dump_directory(hwp_dir, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "skipped":
        print(
            "pyhwp not installed — install via `pip install pyhwp` to dump tables.",
            file=sys.stderr,
        )
        return 0
    print(
        f"\nWrote {args.out} ({summary['tables_dumped']} tables from "
        f"{summary['files_seen']} files).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
