#!/usr/bin/env python3
"""Compare two table-extractor dumps (issue #781, PR-A2).

Reads two JSONL files produced by ``scripts/dump_hwp_tables.py`` (PR-A0)
and ``scripts/extract_hwp_via_upstage.py`` (PR-A1) — or any extractor
that emits the shared
``eval/data/table_extraction_golden.schema.json`` shape — and produces
a side-by-side diff so the labeler can spot disagreements before the
golden labeling pass.

This script intentionally computes only **basic** stats (exact-match
rate, cell-count delta, missing-on-left, missing-on-right). PR-A3 adds
the full RFP-specific metrics (cell F1, boundary F1, merge-cell
preservation, caption attachment).

Off-pipeline. Default HWP loader (ADR 0036) unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _normalize_text(text: str) -> str:
    """NFKC + whitespace-collapse + casefold for cell-text matching.

    Conservative: collapses runs of whitespace and trims, but does not
    drop punctuation (RFP tables use punctuation as meaningful
    separators — e.g. '60점', 'FR-007').
    """
    if text is None:
        return ""
    nfkc = unicodedata.normalize("NFKC", str(text))
    collapsed = " ".join(nfkc.split())
    return collapsed.casefold()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of records. Skips blank lines."""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def index_records(records: Iterable[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    """Index by ``(doc_id, table_index)`` for stable join."""
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for rec in records:
        doc_id = str(rec.get("doc_id", ""))
        table_index = int(rec.get("table_index", 0) or 0)
        out[(doc_id, table_index)] = rec
    return out


def _cells_by_coord(rec: dict[str, Any]) -> dict[tuple[int, int], str]:
    """Index a record's cells by ``(row, col)`` → text (normalized)."""
    out: dict[tuple[int, int], str] = {}
    for cell in rec.get("cells") or []:
        row = int(cell.get("row", 0) or 0)
        col = int(cell.get("col", 0) or 0)
        text = _normalize_text(cell.get("text", ""))
        out[(row, col)] = text
    return out


def diff_pair(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compute per-table diff between two records of the same key.

    Returns a dict with cell-count delta, exact-match rate over the
    intersection of coordinates, and lists of left-only / right-only
    coordinates (cap at 50 entries each to keep the report bounded).
    """
    left_cells = _cells_by_coord(left)
    right_cells = _cells_by_coord(right)
    left_coords = set(left_cells)
    right_coords = set(right_cells)
    common = left_coords & right_coords

    matches = sum(
        1 for coord in common if left_cells[coord] == right_cells[coord]
    )
    exact_match_rate = (matches / len(common)) if common else 0.0

    only_left = sorted(left_coords - right_coords)[:50]
    only_right = sorted(right_coords - left_coords)[:50]
    mismatched = sorted(
        coord for coord in common if left_cells[coord] != right_cells[coord]
    )[:50]

    return {
        "doc_id": left.get("doc_id"),
        "table_index": left.get("table_index"),
        "left_cell_count": len(left_cells),
        "right_cell_count": len(right_cells),
        "cell_count_delta": len(right_cells) - len(left_cells),
        "common_coord_count": len(common),
        "exact_match_count": matches,
        "exact_match_rate": round(exact_match_rate, 4),
        "only_left_coords_sample": [list(c) for c in only_left],
        "only_right_coords_sample": [list(c) for c in only_right],
        "mismatched_coords_sample": [list(c) for c in mismatched],
    }


def compare(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare two extractor dumps and return a summary + per-pair diffs.

    Summary fields:
      * ``left_table_count`` / ``right_table_count``
      * ``common_table_count`` (keys present in both)
      * ``only_left_table_count`` / ``only_right_table_count``
      * ``per_doc`` — table count by doc on each side
      * ``aggregate_exact_match_rate`` — micro-average over common coords
    """
    left_index = index_records(left)
    right_index = index_records(right)
    common_keys = sorted(set(left_index) & set(right_index))
    only_left_keys = sorted(set(left_index) - set(right_index))
    only_right_keys = sorted(set(right_index) - set(left_index))

    per_pair: list[dict[str, Any]] = []
    total_common = 0
    total_matches = 0
    for key in common_keys:
        pair_diff = diff_pair(left_index[key], right_index[key])
        per_pair.append(pair_diff)
        total_common += pair_diff["common_coord_count"]
        total_matches += pair_diff["exact_match_count"]

    aggregate_rate = (total_matches / total_common) if total_common else 0.0

    per_doc_left: dict[str, int] = defaultdict(int)
    per_doc_right: dict[str, int] = defaultdict(int)
    for (doc, _idx) in left_index:
        per_doc_left[doc] += 1
    for (doc, _idx) in right_index:
        per_doc_right[doc] += 1

    summary = {
        "left_table_count": len(left_index),
        "right_table_count": len(right_index),
        "common_table_count": len(common_keys),
        "only_left_table_count": len(only_left_keys),
        "only_right_table_count": len(only_right_keys),
        "only_left_keys_sample": [list(k) for k in only_left_keys[:50]],
        "only_right_keys_sample": [list(k) for k in only_right_keys[:50]],
        "aggregate_common_coord_count": total_common,
        "aggregate_exact_match_count": total_matches,
        "aggregate_exact_match_rate": round(aggregate_rate, 4),
        "per_doc_table_counts": {
            doc: {
                "left": per_doc_left.get(doc, 0),
                "right": per_doc_right.get(doc, 0),
            }
            for doc in sorted(set(per_doc_left) | set(per_doc_right))
        },
    }
    return {"summary": summary, "per_pair": per_pair}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two table-extractor JSONL dumps (issue #781, PR-A2). "
            "Inputs share the eval/data/table_extraction_golden.schema.json "
            "schema. Off-pipeline."
        )
    )
    parser.add_argument(
        "--left",
        type=Path,
        required=True,
        help="Left extractor JSONL (e.g. outputs/table_golden_draft.jsonl).",
    )
    parser.add_argument(
        "--right",
        type=Path,
        required=True,
        help="Right extractor JSONL (e.g. outputs/table_golden_draft_upstage.jsonl).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "outputs" / "table_parser_compare.json",
        help=(
            "Output comparison JSON path "
            "(default: outputs/table_parser_compare.json, gitignored)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for label, path in (("--left", args.left), ("--right", args.right)):
        if not path.exists() or not path.is_file():
            print(
                f"error: {label} does not exist or is not a file: {path}",
                file=sys.stderr,
            )
            return 2

    left = load_jsonl(args.left)
    right = load_jsonl(args.right)
    report = compare(left, right)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(
        f"\nWrote {args.out} ({len(report['per_pair'])} matched table pairs).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
