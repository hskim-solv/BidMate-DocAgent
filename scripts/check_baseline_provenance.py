#!/usr/bin/env python3
"""Verify reports/real100/baseline.aggregate.json's commit is reachable.

The committed baseline pairs metrics with the ``provenance.git_commit``
they were generated at. If that commit is later force-pushed, rebased,
or otherwise made unreachable from ``origin/main``, then every
subsequent ``make real-eval-delta`` silently diffs against a phantom
code state. This script is the gate: CI verifies the baseline's commit
is still an ancestor of ``origin/main`` (or of an explicitly allowed
ref, for PRs that are themselves bumping the baseline).

Because the repo squash-merges, the recorded ``provenance.git_commit``
(the pre-squash PR tip) never lands on main — main gets an
identical-tree commit under a new SHA — so commit ancestry fails for
every PR after a baseline bump. The gate therefore falls back to
``provenance.git_tree``: a baseline is accepted if any commit reachable
from --ref carries that tree (squash-merge invariant, CI-feasible since
only main history is walked). See ADR 0067.

Operational tail of issue #160; tracked as issue #413; squash-twin
durable fix is issue #1222.

Scope (issue #1095): this gate intentionally checks only commit
*reachability*, not config *content* staleness. ``run_manifest.config_sha256``
hashes the eval config passed to ``eval/run_eval.py`` — for the real-data
cycle that is the gitignored, operator-private ``eval/real_config.local.yaml``
(see ``scripts/smoke_real.sh``), not the committed ``eval/config.yaml``. CI
cannot recompute it (the bytes are private under ADR 0005), and an
operator-side hash-mismatch warning would fire on the normal resting state —
the baseline is a deliberately pinned snapshot, every snapshot is generated
dirty, and the local config legitimately drifts between deliberate bumps. So
``config_sha256`` stays reproducibility *metadata*, not a staleness gate; the
real failure modes are covered here (reachability), by the dirty-gate +
strict mode in ``scripts/write_real_eval_baseline.py`` (#1148/#414), and by
the behavioral §5b real-data delta in the PR body.

Exit codes:
  0 — provenance commit OR tree is reachable from --ref (or
      --allow-equal-to).
  1 — neither commit nor tree is reachable (dangling / unmerged).
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


def _extract_provenance_tree(baseline: dict[str, Any]) -> str | None:
    """Return ``provenance.git_tree`` if present and meaningful, else None.

    Older baselines (pre-ADR 0067) have no ``git_tree`` field; the gate
    then falls back to commit-only reachability. ``"unknown"`` (the
    ``build_provenance`` sentinel when git is unavailable) is treated as
    absent so a degenerate snapshot never matches a real tree.
    """
    prov = baseline.get("provenance")
    if not isinstance(prov, dict):
        return None
    tree = prov.get("git_tree")
    if not isinstance(tree, str):
        return None
    tree = tree.strip()
    if not tree or tree == "unknown":
        return None
    return tree


def _tree_reachable(tree: str, ref: str, repo_root: Path) -> bool:
    """True if any commit reachable from ``ref`` has root tree ``tree``.

    Squash-merge invariant: the squash commit on the target branch
    carries the same tree as the dangling pre-squash tip, so matching on
    tree accepts a baseline whose ``git_commit`` no longer lives on the
    branch. Walks only ``ref``'s history (``git log <ref> --format=%T``),
    so it works in CI's sparse + ``fetch-depth:0`` checkout where the
    dangling twin commit object is absent. ``tree`` may be a 12-char
    prefix (the ``build_provenance`` convention), matched against the
    full 40-char ``%T`` output.
    """
    rc, out, _ = _run_git(["log", ref, "--format=%T"], cwd=repo_root)
    if rc != 0 or not out:
        return False
    return any(line.startswith(tree) for line in out.splitlines())


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

    provenance_tree = _extract_provenance_tree(baseline)

    # run_manifest.config_sha256 is deliberately NOT checked for staleness here
    # — see the module docstring's Scope note (#1095). Only the commit/tree
    # reachability below guards self-consistency.
    manifest_sha = _extract_run_manifest_sha(baseline)
    if manifest_sha is not None and manifest_sha != provenance_sha:
        return (
            2,
            "[ERROR] provenance/run_manifest commit mismatch: "
            f"provenance.git_commit={provenance_sha} "
            f"run_manifest.git_commit={manifest_sha}",
        )

    # Tier 1 — commit reachability (precise, backward-compatible). When the
    # commit object is present and is an ancestor of an allowed ref, accept.
    commit_in_db, _, stderr = _run_git(
        ["cat-file", "-e", provenance_sha], cwd=repo_root
    )
    commit_in_db = commit_in_db == 0
    if commit_in_db:
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

    # Tier 2 — tree reachability (squash-merge invariant, ADR 0067). The
    # recorded git_commit dangles the moment a squash-merge lands an
    # identical-tree commit under a new SHA on the target branch. Match on
    # the tree so the baseline stays accepted; only main history is needed,
    # so this works even when the dangling twin object is absent in CI.
    if provenance_tree:
        if _tree_reachable(provenance_tree, ref, repo_root):
            return (
                0,
                f"[OK] baseline.aggregate.json git_tree={provenance_tree} "
                f"is reachable from {ref} (squash-merge-invariant match; "
                f"git_commit={provenance_sha} dangles after squash).",
            )
        if allow_equal_to and _tree_reachable(
            provenance_tree, allow_equal_to, repo_root
        ):
            return (
                0,
                f"[OK] baseline.aggregate.json git_tree={provenance_tree} "
                f"is reachable from {allow_equal_to} (--allow-equal-to escape "
                f"hatch; squash-merge-invariant tree match).",
            )

    if not commit_in_db and not provenance_tree:
        return (
            1,
            f"[ERROR] baseline `provenance.git_commit`={provenance_sha} does not "
            "exist in the git object database and no `provenance.git_tree` is "
            "recorded to fall back on. The commit was likely force-pushed or "
            "rebased away. Run `make real-eval` then "
            f"`make real-eval-baseline-update` at a commit reachable from {ref}. "
            f"({stderr or 'no stderr'})",
        )

    refs_msg = ref if not allow_equal_to else f"{ref} or {allow_equal_to}"
    tree_msg = (
        f" (git_tree={provenance_tree} also not reachable)"
        if provenance_tree
        else ""
    )
    return (
        1,
        f"[ERROR] baseline `provenance.git_commit`={provenance_sha} is not "
        f"reachable from {refs_msg}{tree_msg}. This is the #160 / #413 failure "
        "mode: the baseline points at a code state that no longer lives on the "
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
