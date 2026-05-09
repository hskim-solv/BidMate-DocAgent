#!/usr/bin/env python3
"""Standalone validator for ``data_list.csv`` (issue #51).

Runs the same per-row schema audits as ``scripts/build_index.py`` but does
not load body text, build chunks, or emit an index. The goal is to catch
column / null / duplicate / format / missing-file problems **before** an
indexing run, with a reviewer-friendly report.

Exit codes:
    0  validation passed (no schema issues, no failed rows)
    1  validation surfaced row-level failures
    2  CLI usage error or missing inputs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingestion import FAILURE_TAXONOMY, validate_data_list_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a data_list.csv against the v1 RFP ingestion schema. "
            "See docs/real-data-ingestion.md for column rules."
        )
    )
    parser.add_argument("--metadata_csv", required=True, help="Path to data_list.csv.")
    parser.add_argument(
        "--files_dir",
        required=True,
        help="Directory holding the PDF/HWP files referenced by --metadata_csv.",
    )
    parser.add_argument(
        "--output_path",
        default=None,
        help="Optional path to write the JSON validation report.",
    )
    parser.add_argument(
        "--on_duplicate_doc_id",
        default="fail",
        choices=["fail", "suffix"],
        help=(
            "How duplicate doc_ids should be treated. 'fail' marks the later "
            "row as a duplicate (current default). 'suffix' deterministically "
            "renames the duplicate so downstream eval keeps a stable id."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the summary text printed to stdout.",
    )
    return parser.parse_args()


def render_summary(report: dict) -> str:
    summary = report["summary"]
    schema_issues = report.get("schema_issues") or []
    lines: list[str] = []
    lines.append(f"metadata_csv : {report['metadata_csv']}")
    lines.append(f"files_dir    : {report['files_dir']}")
    lines.append(
        f"rows         : total={summary['total_rows']} "
        f"ok={summary['ok_rows']} failed={summary['failed_rows']}"
    )
    lines.append(f"schema_ok    : {summary['schema_ok']}")
    lines.append(f"on_duplicate : {summary['on_duplicate_doc_id']}")

    if schema_issues:
        lines.append("schema_issues:")
        for issue in schema_issues:
            lines.append(
                f"  - {issue.get('code')}: {issue.get('field')} -> {issue.get('message')}"
            )

    if summary["failure_reasons"]:
        lines.append("failure_reasons:")
        for reason, count in sorted(summary["failure_reasons"].items()):
            description = FAILURE_TAXONOMY.get(reason, {}).get("downstream_risk", "")
            lines.append(f"  - {reason}: {count}  // {description}".rstrip())
            for example in summary["failure_examples"].get(reason, []):
                lines.append(
                    f"      row={example['row_number']} "
                    f"file={example['file_name'] or '-'} "
                    f"doc_id={example['doc_id'] or '-'}"
                )

    if summary["blank_field_warnings"]:
        lines.append("blank_field_warnings:")
        for warning, count in sorted(summary["blank_field_warnings"].items()):
            lines.append(f"  - {warning}: {count}")

    if summary["duplicate_doc_ids"]:
        lines.append("duplicate_doc_ids:")
        for base, rows in summary["duplicate_doc_ids"].items():
            lines.append(f"  - {base}: rows={rows}")

    if summary["file_formats"]:
        lines.append("file_formats:")
        for fmt, count in sorted(summary["file_formats"].items()):
            lines.append(f"  - {fmt}: {count}")
    return "\n".join(lines)


def main() -> int:
    try:
        args = parse_args()
        metadata_csv = Path(args.metadata_csv)
        files_dir = Path(args.files_dir)
        report = validate_data_list_csv(
            metadata_csv,
            files_dir,
            on_duplicate_doc_id=args.on_duplicate_doc_id,
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not args.quiet:
        print(render_summary(report))
        if args.output_path:
            print(f"\n[OK] Validation report written: {args.output_path}")

    summary = report["summary"]
    if not summary["schema_ok"] or summary["failed_rows"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
