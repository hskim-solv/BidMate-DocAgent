#!/usr/bin/env python3
"""ADR 0032 routed-subset spread gate (issue #626).

Reads ``reports/embedding_routed.json`` and checks whether the top-vs-bottom
embedding accuracy spread on the routed subset has crossed the ADR 0032
re-open threshold of +3pp.

Exit codes:
  0 — spread < threshold (saturation cross-validated; MiniLM default lock
      empirically justified; no ADR 0019 re-open trigger needed)
  1 — spread ≥ threshold (ADR 0019 re-open trigger justified; reviewer must
      decide whether to re-open the ADR or acknowledge the measurement)
  2 — file missing / unparseable (measurement not yet run; non-fatal warning
      by default; use --strict to fail on missing file)

Usage:
    python scripts/check_embedding_routed_spread.py
    python scripts/check_embedding_routed_spread.py --report reports/embedding_routed.json
    python scripts/check_embedding_routed_spread.py --strict   # fail if file missing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_REPORT = "reports/embedding_routed.json"
DEFAULT_THRESHOLD_PP = 3.0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help=f"Path to embedding_routed.json (default: {DEFAULT_REPORT})",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 (failure) when the report file is missing instead of warning.",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)

    if not report_path.exists():
        msg = (
            f"⚠️  {report_path} not found. "
            "Run `python scripts/run_routed_measurement.py` to generate it."
        )
        if args.strict:
            print(f"❌ {msg}", file=sys.stderr)
            return 2
        print(msg)
        return 0

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"❌ Could not parse {report_path}: {exc}", file=sys.stderr)
        return 2

    spread_block = data.get("spread") or {}
    spread_pp = spread_block.get("spread_pp")
    threshold_pp = spread_block.get("threshold_pp") or data.get("threshold_pp") or DEFAULT_THRESHOLD_PP
    verdict = spread_block.get("verdict", "unknown")

    if not isinstance(spread_pp, (int, float)):
        print(
            f"⚠️  spread.spread_pp is missing or non-numeric in {report_path}. "
            "Re-run the routed measurement.",
            file=sys.stderr,
        )
        return 2

    print(
        f"ADR 0032 routed-subset spread: {spread_pp:.1f}pp "
        f"(threshold {threshold_pp:.1f}pp, verdict: {verdict})"
    )

    if spread_pp >= threshold_pp:
        print(
            f"\n❌ Spread {spread_pp:.1f}pp ≥ threshold {threshold_pp:.1f}pp — "
            "ADR 0019 re-open trigger justified.\n"
            "   Action required: re-open ADR 0019 or acknowledge in the PR body with\n"
            "   [ALLOW_SPREAD_REGRESSION: <reason>] and update reports/embedding_routed.json.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ Spread {spread_pp:.1f}pp < threshold {threshold_pp:.1f}pp — saturation cross-validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
