#!/usr/bin/env python3
"""Dump verifier↔judge disagreement cases from a synthetic judge local file.

Reads ``reports/synthetic_judge.local.json`` (gitignored, per-case verdicts
produced by ``make synthetic-judge`` with a live backend), filters for cases
where ``judge_status != verifier_status``, and writes two outputs:

* ``reports/judge_disagreements.local.json`` (gitignored, ADR 0005) — full
  per-case disagreement payload including ``judge_reason_short``.
* stdout — committable aggregate: count by ``query_type``, top-3 status-pair
  patterns, and overall disagreement rate.

**ADR 0005 compliance**: only the stdout aggregate is safe to commit (and even
then, it reveals no per-case query/answer text).  The local file stays
gitignored.  Attach the stdout aggregate to your PR description so reviewers
can see the disagreement pattern without accessing private per-case data.

Purpose
-------
The ``agreement_with_verifier`` metric in
``reports/synthetic_judge.aggregate.json`` gives a single number.  That number
doesn't tell you *which* cases disagreed or *why*.  This script surfaces the
pattern so you can:

1. Identify systematic verifier/judge mismatches (Goodhart-safe quality signal).
2. Build the raw data for human-label calibration (ADR 0016 prerequisite).
3. Use disagreements as a targeted eval set for prompt or pipeline iteration.

Usage
-----
    # Requires reports/synthetic_judge.local.json (run make synthetic-judge first)
    make judge-disagreements

    # Or directly:
    python scripts/dump_judge_disagreements.py \\
        --local reports/synthetic_judge.local.json \\
        --output reports/judge_disagreements.local.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LOCAL_PATH = ROOT / "reports" / "synthetic_judge.local.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "judge_disagreements.local.json"
TOP_N_PATTERNS = 3


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def _disagreement_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cases where judge_status != verifier_status."""
    return [
        c for c in cases
        if isinstance(c, dict)
        and c.get("judge_status")
        and c.get("verifier_status")
        and c["judge_status"] != c["verifier_status"]
    ]


def _status_pair(case: dict[str, Any]) -> str:
    """Return a human-readable status-pair label: 'verifier→judge'."""
    return f"{case.get('verifier_status', '?')}→{case.get('judge_status', '?')}"


def analyze_disagreements(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Analyse disagreement cases and return ``(disagreements, aggregate)``.

    Args:
        cases: Full ``cases`` list from ``synthetic_judge.local.json``.

    Returns:
        A tuple of:
        - *disagreements*: list of disagreeing cases (never committed).
        - *aggregate*: committable summary dict with ``n_total``,
          ``n_disagree``, ``disagreement_rate``, ``by_query_type``,
          ``top_status_pairs``.
    """
    total = len([c for c in cases if isinstance(c, dict) and c.get("judge_status")])
    disagreements = _disagreement_cases(cases)

    # Count by query_type
    by_type: dict[str, int] = defaultdict(int)
    pair_counter: Counter[str] = Counter()
    for c in disagreements:
        by_type[str(c.get("query_type") or "unknown")] += 1
        pair_counter[_status_pair(c)] += 1

    top_pairs = [
        {"pair": pair, "count": count}
        for pair, count in pair_counter.most_common(TOP_N_PATTERNS)
    ]

    aggregate: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "n_total": total,
        "n_disagree": len(disagreements),
        "disagreement_rate": (
            round(len(disagreements) / total, 4) if total > 0 else None
        ),
        "by_query_type": dict(sorted(by_type.items())),
        "top_status_pairs": top_pairs,
    }
    return disagreements, aggregate


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _build_local_payload(
    disagreements: list[dict[str, Any]],
    source_meta: dict[str, Any],
) -> dict[str, Any]:
    """Build the gitignored per-case disagreement file payload."""
    return {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "source_backend": source_meta.get("backend", "unknown"),
        "source_model": source_meta.get("model", "unknown"),
        "source_generated_at": source_meta.get("generated_at", "unknown"),
        "cases": [
            {
                "id": c.get("id"),
                "query_type": c.get("query_type"),
                "verifier_status": c.get("verifier_status"),
                "judge_status": c.get("judge_status"),
                "judge_grounded": c.get("judge_grounded"),
                "judge_reason_short": c.get("judge_reason_short", ""),
                "faithfulness": c.get("faithfulness"),
                "answer_relevance": c.get("answer_relevance"),
            }
            for c in disagreements
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--local",
        default=str(DEFAULT_LOCAL_PATH),
        help=(
            "Path to reports/synthetic_judge.local.json "
            "(gitignored per-case verdicts from make synthetic-judge)."
        ),
    )
    ap.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Where to write the per-case disagreement payload (gitignored). "
            "Default: reports/judge_disagreements.local.json"
        ),
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the aggregate JSON from stdout (useful in scripts).",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    local_path = Path(args.local)
    if not local_path.exists():
        print(
            f"[ERROR] Local judge file not found: {local_path}\n"
            "Run `make synthetic-judge` with a live backend first.\n"
            "  export BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible\n"
            "  make eval && make synthetic-judge",
            file=sys.stderr,
        )
        return 2

    local_data = json.loads(local_path.read_text(encoding="utf-8"))
    cases = local_data.get("cases") or []
    if not cases:
        print("[WARN] No cases found in the local judge file.", file=sys.stderr)

    disagreements, aggregate = analyze_disagreements(cases)

    # Write gitignored local payload
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    local_payload = _build_local_payload(disagreements, local_data)
    output_path.write_text(
        json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Disagreement cases written: {output_path}", file=sys.stderr)

    if not args.quiet:
        print(json.dumps(aggregate, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
