#!/usr/bin/env python3
"""Append a single aggregate snapshot to reports/history/ (#166).

Reads ``reports/eval_summary.json`` (output of ``make eval``), extracts
the ADR 0005-safe aggregate via ``scripts.run_real_eval_delta.extract_aggregate``,
and writes a chronological snapshot file at
``reports/history/<YYYYMMDDTHHMMSSZ>_<sha12>.aggregate.json``.

Intended cadence: every merge to main (CI). One file per commit means
the leaderboard time-series has one point per real change.

Aggregate-only by construction — the source eval_summary.json may
contain case_results (case-level fields), but the extractor drops
them before writing. Same privacy boundary as
``scripts/write_real_eval_baseline.py`` (real-data sibling).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._utils import build_provenance, make_run_id  # noqa: E402
from scripts.run_real_eval_delta import extract_aggregate  # noqa: E402

EVAL_SUMMARY = ROOT / "reports" / "eval_summary.json"
HISTORY_DIR = ROOT / "reports" / "history"


def main() -> int:
    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make eval` first.",
            file=sys.stderr,
        )
        return 2
    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    provenance = build_provenance()
    agg["provenance"] = provenance
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = HISTORY_DIR / f"{make_run_id(provenance)}.aggregate.json"
    out_path.write_text(
        json.dumps(agg, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
