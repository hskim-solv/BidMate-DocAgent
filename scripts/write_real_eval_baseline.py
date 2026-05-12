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

Strict mode (issue #414): pass ``--strict`` or set
``BIDMATE_BASELINE_STRICT=1`` to escalate the two existing provenance
warnings (no eval-side provenance block; eval/baseline SHA skew per
issue #160) from stderr-only to hard failures (exit 2, no baseline
written). Default behavior is unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._utils import build_provenance, make_run_id
from scripts.run_real_eval_delta import extract_aggregate

STRICT_ENV_VAR = "BIDMATE_BASELINE_STRICT"
_TRUTHY = {"1", "true", "yes"}

EVAL_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
BASELINE_PATH = ROOT / "reports" / "real100" / "baseline.aggregate.json"
HISTORY_DIR = ROOT / "reports" / "real100" / "history"
JUDGE_LOCAL = ROOT / "reports" / "real100" / "judge.local.json"


def _resolve_strict(flag: bool) -> bool:
    """Effective strict mode = CLI flag OR ``BIDMATE_BASELINE_STRICT`` truthy.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``. Any other
    value of the env var is treated as falsy, including ``0``, ``false``,
    ``no``, the empty string, or anything unrecognized.
    """
    if flag:
        return True
    raw = os.environ.get(STRICT_ENV_VAR, "").strip().lower()
    return raw in _TRUTHY


def _warn_if_stale(
    eval_prov: dict[str, object] | None,
    baseline_prov: dict[str, object],
    strict: bool = False,
) -> None:
    """Warn — or, in strict mode, hard-fail — when the eval was generated
    at a different code state than the baseline is being written at.

    This is the failure mode that produced issue #160: ``make real-eval``
    runs at commit X, then ``make real-eval-baseline-update`` runs at
    commit Y, and the baseline silently captures Y's provenance with X's
    metrics. Default is warn (legitimate workflows like docs-only changes
    between runs shouldn't be blocked). Strict mode (``--strict`` or
    ``BIDMATE_BASELINE_STRICT=1``, issue #414) escalates both branches
    to ``SystemExit(2)`` — for CI/pre-push and other gates that require
    a self-consistent baseline.
    """
    level = "ERROR" if strict else "WARN"
    if not isinstance(eval_prov, dict):
        print(
            f"[{level}] eval_summary.json has no `provenance` block — cannot verify "
            "the eval was run at the current HEAD. The baseline's provenance "
            "will reflect the current HEAD, not the eval-run code state. "
            "Re-run `make real-eval` at HEAD to get a self-consistent baseline.",
            file=sys.stderr,
        )
        if strict:
            raise SystemExit(2)
        return
    eval_sha = str(eval_prov.get("git_commit") or "").strip()
    baseline_sha = str(baseline_prov.get("git_commit") or "").strip()
    if not eval_sha or not baseline_sha or eval_sha == baseline_sha:
        return
    print(
        f"[{level}] Provenance skew detected:\n"
        f"        eval_summary.json was generated at git_commit={eval_sha}\n"
        f"        baseline is being written at  git_commit={baseline_sha}\n"
        f"        The baseline's provenance will not match the eval's code state.\n"
        f"        This is the #160 failure mode. Re-run `make real-eval` at HEAD\n"
        f"        before continuing, or accept the skew if you understand the cause.",
        file=sys.stderr,
    )
    if strict:
        raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Escalate provenance warnings (missing eval provenance; eval/"
            "baseline SHA skew per issue #160) to hard failures: exit 2, "
            f"baseline NOT written. Equivalent to {STRICT_ENV_VAR}=1."
        ),
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    strict = _resolve_strict(args.strict)

    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make real-eval` first.",
            file=sys.stderr,
        )
        return 2

    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    eval_prov = raw.get("provenance") if isinstance(raw, dict) else None
    baseline_prov = build_provenance()
    _warn_if_stale(eval_prov, baseline_prov, strict=strict)
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
    history_path = HISTORY_DIR / f"{make_run_id(baseline_prov)}.aggregate.json"
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
