#!/usr/bin/env python3
"""Extract HWP tables via Upstage Document Parser (issue #773, PR-A1).

Companion to ``scripts/dump_hwp_tables.py`` (PR-A0). Produces the same
golden-draft JSONL shape but via Upstage's layout-aware Document Parser
instead of pyhwp's event stream. Used downstream by PR-A2's comparison
script (``pyhwp_native_tables`` vs ``upstage_document_parser``) on the
human-labeled golden.

Off-pipeline tool. Default HWP loader (ADR 0036) is unchanged.
``ingestion.py`` is **not** touched on purpose: keeping the Upstage path
out of the load-bearing dispatch avoids the §5b friction and means the
script can be iterated independently of the runtime path.

Gracefully skips when ``UPSTAGE_API_KEY`` is unset so the script can be
imported / ``--help``-ed without secrets. Per-file API failures are
isolated; the failing file's name + error appear in the summary's
``failures`` list instead of being raised.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


UPSTAGE_API_URL = "https://api.upstage.ai/v1/document-ai/document-parse"
DEFAULT_MODEL = "document-parse"
DEFAULT_TIMEOUT_S = 120.0
EXTRACTOR_TAG = "upstage_document_parser"
SKIP_REASON_KEY_MISSING = "upstage_api_key_missing"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_api_key() -> str | None:
    key = os.environ.get("UPSTAGE_API_KEY", "").strip()
    return key or None


def _has_nonempty_cells(table: dict[str, Any]) -> bool:
    for cell in table.get("cells") or []:
        if str(cell.get("text", "")).strip():
            return True
    return False


def parse_table_html(html: str) -> tuple[int, int, list[dict[str, Any]]]:
    """Parse one ``<table>`` HTML fragment into ``(rows, cols, cells)``.

    ``cells`` is a flat list of
    ``{"row", "col", "rowspan", "colspan", "text"}`` matching the PR-A0
    schema. An internal occupancy grid handles ``rowspan`` so that a
    later cell in the same row gets the right ``col`` index.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table") or soup
    grid: list[list[bool]] = []
    cells: list[dict[str, Any]] = []
    max_cols = 0

    rows = table.find_all("tr")
    for row_idx, tr in enumerate(rows):
        while len(grid) <= row_idx:
            grid.append([])

        col_idx = 0
        for td in tr.find_all(["td", "th"]):
            # Skip past columns already occupied by an earlier rowspan.
            while col_idx < len(grid[row_idx]) and grid[row_idx][col_idx]:
                col_idx += 1

            rowspan = int(td.get("rowspan", 1) or 1)
            colspan = int(td.get("colspan", 1) or 1)
            text = td.get_text(separator=" ", strip=True)

            # Mark this cell and any spanned rows/cols as occupied.
            for dr in range(rowspan):
                rr = row_idx + dr
                while len(grid) <= rr:
                    grid.append([])
                while len(grid[rr]) < col_idx + colspan:
                    grid[rr].append(False)
                for dc in range(colspan):
                    grid[rr][col_idx + dc] = True

            cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "text": text,
                }
            )
            max_cols = max(max_cols, col_idx + colspan)
            col_idx += colspan

    return len(rows), max_cols, cells


def extract_tables_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk an Upstage response and return per-table records.

    Tolerates two known shape variants:
      * top-level ``elements[*].html`` (newer responses)
      * nested ``elements[*].content.html`` (older responses)

    Each returned record has the keys consumed by ``dump_record``:
    ``table_index`` (0-indexed within the doc), ``rows``, ``cols``,
    ``page`` (or None), ``cells``.
    """
    elements = response.get("elements") or []
    tables: list[dict[str, Any]] = []
    table_index = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        category = element.get("category") or element.get("type") or ""
        if str(category).lower() != "table":
            continue
        html = element.get("html") or ""
        if not html:
            content = element.get("content")
            if isinstance(content, dict):
                html = content.get("html") or ""
        if not html:
            continue
        rows, cols, cells = parse_table_html(html)
        if not cells:
            continue
        page = element.get("page")
        tables.append(
            {
                "table_index": table_index,
                "rows": rows,
                "cols": cols,
                "page": int(page) if isinstance(page, int) else None,
                "cells": cells,
            }
        )
        table_index += 1
    return tables


def dump_record(
    doc_id: str,
    source_path: Path,
    table: dict[str, Any],
    *,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Build one golden-draft record. Same schema as PR-A0."""
    return {
        "doc_id": doc_id,
        "source_path": str(source_path),
        "page": table.get("page"),
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


def call_upstage(
    source_path: Path,
    *,
    api_key: str,
    api_url: str = UPSTAGE_API_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """POST one file to the Upstage Document Parse endpoint.

    Returns the parsed JSON body. Raises ``requests.HTTPError`` on
    non-2xx status; callers in ``extract_directory`` catch and convert
    to per-file failures.
    """
    http = session or requests.Session()
    with source_path.open("rb") as fh:
        files = {
            "document": (source_path.name, fh, "application/octet-stream"),
        }
        data = {
            "model": DEFAULT_MODEL,
            "ocr": "auto",
            "output_formats": json.dumps(["html"]),
            "coordinates": "false",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = http.post(
            api_url,
            headers=headers,
            files=files,
            data=data,
            timeout=timeout_s,
        )
    resp.raise_for_status()
    return resp.json()


def iter_hwp_files(hwp_dir: Path) -> Iterable[Path]:
    return sorted(p for p in hwp_dir.glob("*.hwp") if p.is_file())


def extract_directory(
    hwp_dir: Path,
    out_path: Path,
    *,
    api_key: str | None = None,
    api_url: str = UPSTAGE_API_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Iterate ``hwp_dir`` and emit one JSONL line per non-empty table.

    Returns a summary dict (``status``, ``files_seen``, ``tables_dumped``,
    ``failures``). Never raises on per-file errors.
    """
    resolved_key = api_key if api_key is not None else _get_api_key()
    if not resolved_key:
        return {
            "status": "skipped",
            "reason": SKIP_REASON_KEY_MISSING,
            "files_seen": 0,
            "tables_dumped": 0,
            "failures": [],
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_hwp_files(hwp_dir))
    tables_dumped = 0
    failures: list[dict[str, str]] = []

    with out_path.open("w", encoding="utf-8") as fh:
        for source in files:
            try:
                response = call_upstage(
                    source,
                    api_key=resolved_key,
                    api_url=api_url,
                    timeout_s=timeout_s,
                    session=session,
                )
                tables = extract_tables_from_response(response)
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
            "Extract HWP tables via Upstage Document Parser as draft golden "
            "JSONL (issue #773, PR-A1 of HWP RAG table experiment). "
            "Off-pipeline; companion to scripts/dump_hwp_tables.py. "
            "Requires UPSTAGE_API_KEY env var to actually call the API."
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
        default=REPO_ROOT / "outputs" / "table_golden_draft_upstage.jsonl",
        help=(
            "Output JSONL path "
            "(default: outputs/table_golden_draft_upstage.jsonl, gitignored)."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=UPSTAGE_API_URL,
        help="Override the Upstage Document Parse endpoint URL.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="Per-file timeout in seconds (default: 120).",
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
    summary = extract_directory(
        hwp_dir,
        args.out,
        api_url=args.api_url,
        timeout_s=args.timeout_s,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "skipped":
        print(
            "UPSTAGE_API_KEY not set — export the key to enable Upstage calls.",
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
