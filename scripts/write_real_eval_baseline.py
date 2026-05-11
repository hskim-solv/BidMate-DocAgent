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
JUDGE_LOCAL = ROOT / "reports" / "real100" / "judge.local.json"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT
    )
    return result.stdout.strip()


def provenance() -> dict[str, object]:
    """Return a provenance block for the current git HEAD.

    Shared by the baseline writer (this script) and the eval runner
    (``eval/run_eval.py``). Format is intentionally narrow: 12-char SHA,
    dirty flag, ISO-8601 UTC timestamp.
    """
    sha = _git("rev-parse", "HEAD")[:12] or "unknown"
    dirty = _git("status", "--porcelain") != ""
    return {
        "git_commit": sha,
        "git_dirty": bool(dirty),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _run_id(prov: dict[str, object]) -> str:
    # YYYYMMDDTHHMMSSZ_<sha12>
    ts = (
        str(prov.get("generated_at"))
        .replace("-", "")
        .replace(":", "")
        .split(".")[0]  # drop fractional seconds
    )
    if not ts.endswith("Z"):
        ts += "Z"
    sha = str(prov.get("git_commit") or "unknown")[:12]
    return f"{ts}_{sha}"


def _warn_if_stale(
    eval_prov: dict[str, object] | None, baseline_prov: dict[str, object]
) -> None:
    """Warn loudly if the eval was generated at a different code state
    than the baseline is being written at.

    This is the failure mode that produced issue #160: ``make real-eval``
    runs at commit X, then ``make real-eval-baseline-update`` runs at
    commit Y, and the baseline silently captures Y's provenance with X's
    metrics. We warn rather than fail because legitimate workflows
    (e.g., docs-only changes between runs) shouldn't be blocked, but we
    want the failure mode to be loud and self-diagnosing.
    """
    if not isinstance(eval_prov, dict):
        print(
            "[WARN] eval_summary.json has no `provenance` block — cannot verify "
            "the eval was run at the current HEAD. The baseline's provenance "
            "will reflect the current HEAD, not the eval-run code state. "
            "Re-run `make real-eval` at HEAD to get a self-consistent baseline.",
            file=sys.stderr,
        )
        return
    eval_sha = str(eval_prov.get("git_commit") or "").strip()
    baseline_sha = str(baseline_prov.get("git_commit") or "").strip()
    if not eval_sha or not baseline_sha or eval_sha == baseline_sha:
        return
    print(
        f"[WARN] Provenance skew detected:\n"
        f"        eval_summary.json was generated at git_commit={eval_sha}\n"
        f"        baseline is being written at  git_commit={baseline_sha}\n"
        f"        The baseline's provenance will not match the eval's code state.\n"
        f"        This is the #160 failure mode. Re-run `make real-eval` at HEAD\n"
        f"        before continuing, or accept the skew if you understand the cause.",
        file=sys.stderr,
    )


def main() -> int:
    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make real-eval` first.",
            file=sys.stderr,
        )
        return 2

    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    eval_prov = raw.get("provenance") if isinstance(raw, dict) else None
    baseline_prov = provenance()
    _warn_if_stale(eval_prov, baseline_prov)
    agg["provenance"] = baseline_prov

    # If a judge run is present (ADR 0006), fold its aggregate into the
    # baseline. The per-case judge file stays local; only the
    # committable aggregate keys are copied here.
    if JUDGE_LOCAL.exists():
        from collections import Counter

        judge_payload = json.loads(JUDGE_LOCAL.read_text(encoding="utf-8"))
        cases = judge_payload.get("cases") or []
        statuses = [c.get("judge_status") for c in cases if c.get("judge_status")]
        grounded = [bool(c.get("judge_grounded")) for c in cases]
        agreements = [bool(c.get("agrees")) for c in cases if c.get("agrees") is not None]
        agg["judge"] = {
            "status_distribution": dict(Counter(statuses)),
            "grounded_rate": (sum(grounded) / len(grounded)) if grounded else None,
            "agreement_with_verifier": (
                sum(agreements) / len(agreements) if agreements else None
            ),
            "n": len(cases),
            "backend": str(judge_payload.get("backend") or "unknown"),
            "model": str(judge_payload.get("model") or "unknown"),
        }

    serialized = json.dumps(agg, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(serialized, encoding="utf-8")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = HISTORY_DIR / f"{_run_id(baseline_prov)}.aggregate.json"
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
