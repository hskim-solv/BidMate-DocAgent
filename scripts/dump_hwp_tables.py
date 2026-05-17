#!/usr/bin/env python3
"""ADR 0049 superseded stub for the pyhwp table-dump tool (was issue #728).

The original implementation called ``ingestion._extract_hwp_native_with_tables``
to dump per-cell table JSONL for human labeling. ADR 0049 replaced the
pyhwp backend with kordoc (npm subprocess), whose Markdown output already
contains HTML ``<table>`` with ``rowspan``/``colspan`` — the structured
surface this script was inventing. The dump pipeline is therefore
obsolete; the kordoc Markdown itself is the labeling input.

Kept as a stub so existing references (docs, prior PR descriptions)
still resolve to a file rather than 404. Invocation prints a one-line
explanation and exits non-zero so any forgotten cron / CI hook fails
loudly rather than silently regressing.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "scripts/dump_hwp_tables.py is superseded by ADR 0049 — pyhwp/hwp5 backend "
        "removed; use kordoc Markdown output (data/files_kordoc/) for table labeling.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
