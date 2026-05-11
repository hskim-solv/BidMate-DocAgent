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

import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_real_eval_delta import extract_aggregate  # noqa: E402

EVAL_SUMMARY = ROOT / "reports" / "eval_summary.json"
HISTORY_DIR = ROOT / "reports" / "history"


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=ROOT, check=False
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _provenance() -> dict[str, object]:
    sha = _git("rev-parse", "HEAD")[:12] or "unknown"
    dirty = _git("status", "--porcelain") != ""
    return {
        "git_commit": sha,
        "git_dirty": bool(dirty),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _run_id(provenance: dict[str, object]) -> str:
    ts = (
        str(provenance.get("generated_at"))
        .replace("-", "")
        .replace(":", "")
        .split(".")[0]
    )
    if not ts.endswith("Z"):
        ts += "Z"
    sha = str(provenance.get("git_commit") or "unknown")[:12]
    return f"{ts}_{sha}"


def main() -> int:
    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make eval` first.",
            file=sys.stderr,
        )
        return 2
    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    provenance = _provenance()
    agg["provenance"] = provenance
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = HISTORY_DIR / f"{_run_id(provenance)}.aggregate.json"
    out_path.write_text(
        json.dumps(agg, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
