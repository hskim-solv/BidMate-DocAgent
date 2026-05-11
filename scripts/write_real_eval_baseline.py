#!/usr/bin/env python3
"""Write the committable baseline + history snapshot for real-data eval.

Reads ``reports/real100/eval_summary.json`` (gitignored, local-only),
extracts the aggregate-only allowlisted fields via
:func:`scripts.run_real_eval_delta.extract_aggregate`, and writes:

* ``reports/real100/baseline.aggregate.json`` — the *current* baseline
  used by ``make real-eval-delta``.
* ``reports/real100/history/<YYYYMMDDTHHMMSSZ>_<sha>.aggregate.json``
  — an append-only chronological archive.

Both files are committable under the ADR 0005 boundary (the gitignore
allowlist on ``baseline.aggregate.json`` and ``history/*.aggregate.json``
makes them visible to git).

Intended cadence: deliberate, after a decision lands (PR merged,
threshold tightened). Not every run.
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

from scripts.run_real_eval_delta import extract_aggregate

EVAL_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
BASELINE_PATH = ROOT / "reports" / "real100" / "baseline.aggregate.json"
HISTORY_DIR = ROOT / "reports" / "real100" / "history"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT
    )
    return result.stdout.strip()


def _provenance() -> dict[str, object]:
    sha = _git("rev-parse", "HEAD")[:12] or "unknown"
    dirty = _git("status", "--porcelain") != ""
    return {
        "git_commit": sha,
        "git_dirty": bool(dirty),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _run_id(provenance: dict[str, object]) -> str:
    # YYYYMMDDTHHMMSSZ_<sha12>
    ts = (
        str(provenance.get("generated_at"))
        .replace("-", "")
        .replace(":", "")
        .split(".")[0]  # drop fractional seconds
    )
    if not ts.endswith("Z"):
        ts += "Z"
    sha = str(provenance.get("git_commit") or "unknown")[:12]
    return f"{ts}_{sha}"


def main() -> int:
    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make real-eval` first.",
            file=sys.stderr,
        )
        return 2

    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    provenance = _provenance()
    agg["provenance"] = provenance

    serialized = json.dumps(agg, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(serialized, encoding="utf-8")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = HISTORY_DIR / f"{_run_id(provenance)}.aggregate.json"
    history_path.write_text(serialized, encoding="utf-8")

    print(f"[OK] Updated {BASELINE_PATH.relative_to(ROOT)}")
    print(f"[OK] Archived {history_path.relative_to(ROOT)}")
    print(
        "\nReview with `git diff reports/real100/` and "
        "`python3 scripts/render_real_eval_history.py` "
        "before committing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
