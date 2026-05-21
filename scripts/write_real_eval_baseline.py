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
``BIDMATE_BASELINE_STRICT=1`` to escalate the existing provenance
warnings (no eval-side provenance block; eval/baseline SHA skew per
issue #160; dirty worktree per issue #1148) from stderr-only to hard
failures (exit 2, no baseline written). Default behavior is unchanged.

Dirty gate (issue #1148): the SHA-only skew check passes whenever the
eval and the baseline share a commit, but says nothing about
*uncommitted* changes at that commit. An eval run from a dirty worktree
(uncommitted scorer/config/code) therefore bakes unreproducible metrics
into the committed baseline even under ``--strict``. The dirty gate
inspects the eval-side ``provenance``/``run_manifest`` dirty flags and
the write-time worktree; ``--allow-dirty`` /
``BIDMATE_BASELINE_ALLOW_DIRTY=1`` is the documented escape hatch for a
deliberate dirty baseline.
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
ALLOW_DIRTY_ENV_VAR = "BIDMATE_BASELINE_ALLOW_DIRTY"
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


def _resolve_allow_dirty(flag: bool) -> bool:
    """Effective allow-dirty = ``--allow-dirty`` flag OR
    ``BIDMATE_BASELINE_ALLOW_DIRTY`` truthy.

    Uses the same truthy set as :func:`_resolve_strict` (``1``/``true``/
    ``yes``, case-insensitive); any other value is falsy.
    """
    if flag:
        return True
    raw = os.environ.get(ALLOW_DIRTY_ENV_VAR, "").strip().lower()
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


def _warn_if_dirty(
    eval_prov: dict[str, object] | None,
    run_manifest: dict[str, object] | None,
    baseline_prov: dict[str, object],
    *,
    strict: bool = False,
    allow_dirty: bool = False,
) -> None:
    """Warn — or, in strict mode, hard-fail — when the baseline would
    capture an unreproducible *dirty* code state.

    The SHA-only skew check (:func:`_warn_if_stale`) passes whenever the
    eval and the baseline share a commit, but says nothing about
    uncommitted changes *at* that commit. An eval run from a dirty
    worktree (uncommitted scorer/config/code) therefore bakes
    unreproducible metrics into the committed baseline even under
    ``--strict`` — the residual #160-class hole reported in issue #1148.

    Three dirty signals are inspected: the eval-side ``provenance`` and
    ``run_manifest`` blocks from ``eval_summary.json`` (the eval was run
    dirty) and ``baseline_prov`` (the baseline is being written from a
    dirty worktree). Any true flag warns; under ``strict`` it is a hard
    failure (exit 2, no baseline written). ``allow_dirty``
    (``--allow-dirty`` / ``BIDMATE_BASELINE_ALLOW_DIRTY=1``) is the
    documented override for a deliberate dirty baseline.
    """
    if allow_dirty:
        return
    dirty_sources: list[str] = []
    if isinstance(eval_prov, dict) and eval_prov.get("git_dirty"):
        dirty_sources.append("eval_summary.json `provenance` (git_dirty=true)")
    if isinstance(run_manifest, dict) and run_manifest.get("git_dirty"):
        dirty_sources.append("eval_summary.json `run_manifest` (git_dirty=true)")
    if isinstance(baseline_prov, dict) and baseline_prov.get("git_dirty"):
        dirty_sources.append("baseline write-time worktree (git_dirty=true)")
    if not dirty_sources:
        return
    level = "ERROR" if strict else "WARN"
    detail = "".join(f"        - {src}\n" for src in dirty_sources)
    print(
        f"[{level}] Dirty worktree detected — the baseline would capture an\n"
        f"        unreproducible code state:\n"
        f"{detail}"
        f"        Re-run `make real-eval` and the baseline update from a clean\n"
        f"        worktree (commit or stash first). This is the residual #160\n"
        f"        failure mode the SHA-only skew check does not catch (#1148).\n"
        f"        Override with --allow-dirty / {ALLOW_DIRTY_ENV_VAR}=1 only for\n"
        f"        a deliberate dirty baseline.",
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
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Override the dirty-worktree gate (issue #1148): write the "
            "baseline even when the eval provenance/run_manifest or the "
            "write-time worktree is dirty. For a deliberate dirty baseline "
            f"only. Equivalent to {ALLOW_DIRTY_ENV_VAR}=1."
        ),
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    strict = _resolve_strict(args.strict)
    allow_dirty = _resolve_allow_dirty(args.allow_dirty)

    if not EVAL_SUMMARY.exists():
        print(
            f"[ERROR] {EVAL_SUMMARY} not found. Run `make real-eval` first.",
            file=sys.stderr,
        )
        return 2

    raw = json.loads(EVAL_SUMMARY.read_text(encoding="utf-8"))
    agg = extract_aggregate(raw)
    eval_prov = raw.get("provenance") if isinstance(raw, dict) else None
    run_manifest = raw.get("run_manifest") if isinstance(raw, dict) else None
    baseline_prov = build_provenance()
    _warn_if_stale(eval_prov, baseline_prov, strict=strict)
    _warn_if_dirty(
        eval_prov, run_manifest, baseline_prov, strict=strict, allow_dirty=allow_dirty
    )
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
