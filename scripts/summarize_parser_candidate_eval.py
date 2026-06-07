#!/usr/bin/env python3
"""Summarize a parser-candidate eval run into aggregate reviewer artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_candidate_eval import (  # noqa: E402
    CandidateEvalError,
    SUMMARY_FILENAME,
    build_run_summary,
    report_dir_default,
    write_json,
    write_markdown_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize parser candidate eval artifacts.")
    parser.add_argument("--run-id", required=True, help="Run id to summarize.")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Raw/private run dir. Defaults to data/private/real100_v2/parser_candidate_eval/<run-id>.",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Aggregate output dir. Defaults to reports/parser_candidate_eval/<run-id>.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else REPO_ROOT / "data/private/real100_v2/parser_candidate_eval" / args.run_id
    report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(args.run_id)
    try:
        summary = build_run_summary(run_dir)
    except CandidateEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write_json(report_dir / SUMMARY_FILENAME, summary)
    write_markdown_summary(report_dir / "README.md", summary)
    print(report_dir / SUMMARY_FILENAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
