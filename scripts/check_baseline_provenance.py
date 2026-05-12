#!/usr/bin/env python3
"""Verify reports/real100/baseline.aggregate.json's commit is reachable.

The committed baseline pairs metrics with the ``provenance.git_commit``
they were generated at. If that commit is later force-pushed, rebased,
or otherwise made unreachable from ``origin/main``, then every
subsequent ``make real-eval-delta`` silently diffs against a phantom
code state. This script is the gate: CI verifies the baseline's SHA is
still an ancestor of ``origin/main`` (or of an explicitly allowed ref,
for PRs that are themselves bumping the baseline).

Operational tail of issue #160; tracked as issue #413.

Exit codes:
  0 — provenance.git_commit is reachable from --ref (or --allow-equal-to).
  1 — SHA is not reachable from any allowed ref (dangling / unmerged).
  2 — config error: baseline missing/malformed, provenance/run_manifest
      commit mismatch, or git unavailable.

Usage:
  python scripts/check_baseline_provenance.py
  python scripts/check_baseline_provenance.py --ref origin/main
  python scripts/check_baseline_provenance.py --allow-equal-to <pr-head-sha>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = "reports/real100/baseline.aggregate.json"
DEFAULT_REF = "origin/main"


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return (127, "", f"git executable not available: {exc}")
    return (result.returncode, result.stdout.strip(), result.stderr.strip())


def _extract_provenance_sha(baseline: dict[str, Any]) -> str:
    prov = baseline.get("provenance")
    if not isinstance(prov, dict):
        raise ValueError("baseline has no `provenance` block")
    sha = prov.get("git_commit")
    if not isinstance(sha, str) or not sha.strip():
        raise ValueError("baseline `provenance.git_commit` is empty or non-string")
    return sha.strip()


def _extract_run_manifest_sha(baseline: dict[str, Any]) -> str | None:
    manifest = baseline.get("run_manifest")
    if not isinstance(manifest, dict):
        return None
    sha = manifest.get("git_commit")
    if not isinstance(sha, str) or not sha.strip():
        return None
    return sha.strip()


def check(
    baseline_path: Path,
    ref: str,
    allow_equal_to: str | None,
    repo_root: Path = ROOT_DIR,
) -> tuple[int, str]:
    """Return ``(exit_code, message)``.

    See module docstring for exit-code semantics.
    """
    if not baseline_path.exists():
        return (2, f"[ERROR] baseline not found: {baseline_path}")
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (2, f"[ERROR] baseline JSON malformed at {baseline_path}: {exc}")
    if not isinstance(baseline, dict):
        return (2, f"[ERROR] baseline must be a JSON object: {baseline_path}")

    try:
        provenance_sha = _extract_provenance_sha(baseline)
    except ValueError as exc:
        return (2, f"[ERROR] {exc}")

    manifest_sha = _extract_run_manifest_sha(baseline)
    if manifest_sha is not None and manifest_sha != provenance_sha:
        return (
            2,
            "[ERROR] provenance/run_manifest commit mismatch: "
            f"provenance.git_commit={provenance_sha} "
            f"run_manifest.git_commit={manifest_sha}",
        )

    rc, _, stderr = _run_git(["cat-file", "-e", provenance_sha], cwd=repo_root)
    if rc != 0:
        return (
            1,
            f"[ERROR] baseline `provenance.git_commit`={provenance_sha} does not "
            "exist in the git object database. The commit was likely "
            "force-pushed or rebased away. "
            "Run `make real-eval` then `make real-eval-baseline-update` at a "
            f"commit reachable from {ref}. ({stderr or 'no stderr'})",
        )

    rc, _, _ = _run_git(
        ["merge-base", "--is-ancestor", provenance_sha, ref], cwd=repo_root
    )
    if rc == 0:
        return (
            0,
            f"[OK] baseline.aggregate.json git_commit={provenance_sha} "
            f"is reachable from {ref}.",
        )

    if allow_equal_to:
        rc, _, _ = _run_git(
            ["merge-base", "--is-ancestor", provenance_sha, allow_equal_to],
            cwd=repo_root,
        )
        if rc == 0:
            return (
                0,
                f"[OK] baseline.aggregate.json git_commit={provenance_sha} "
                f"is reachable from {allow_equal_to} (--allow-equal-to escape "
                f"hatch; will be ancestor of {ref} after merge).",
            )

    refs_msg = ref if not allow_equal_to else f"{ref} or {allow_equal_to}"
    return (
        1,
        f"[ERROR] baseline `provenance.git_commit`={provenance_sha} is not "
        f"reachable from {refs_msg}. This is the #160 / #413 failure mode: "
        "the baseline points at a code state that no longer lives on the "
        "target branch. Run `make real-eval` then "
        "`make real-eval-baseline-update` on the current HEAD before merging.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help="Path to baseline aggregate JSON (default: %(default)s).",
    )
    ap.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help="Ref that must contain the baseline's commit (default: %(default)s).",
    )
    ap.add_argument(
        "--allow-equal-to",
        default=None,
        metavar="SHA",
        help=(
            "Additional ref/SHA that the baseline commit may be an ancestor of. "
            "Use for PRs that themselves bump the baseline: pass the PR head "
            "SHA so the in-flight commit is accepted while the SHA is still "
            "outside origin/main."
        ),
    )
    ap.add_argument(
        "--repo-root",
        default=None,
        help=argparse.SUPPRESS,
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root) if args.repo_root else ROOT_DIR
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = repo_root / baseline_path
    exit_code, message = check(baseline_path, args.ref, args.allow_equal_to, repo_root)
    stream = sys.stdout if exit_code == 0 else sys.stderr
    print(message, file=stream)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
