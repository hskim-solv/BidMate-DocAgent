#!/usr/bin/env python3
"""Fail-soft sync for the canonical Desktop checkout's main branch.

Auto-ship calls this after a successful merge so the long-lived Desktop clone
does not lag behind GitHub main. The script never resets or discards local
work: it only fast-forwards `main` when that is safe.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


DEFAULT_REPO = Path("/Users/hskim/Desktop/projects/BidMate-DocAgent")


@dataclass(frozen=True)
class SyncResult:
    status: str
    reason: str
    exit_code: int


def _run_git(repo: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def _git_stdout(repo: Path, args: list[str]) -> str:
    return _run_git(repo, args, check=True).stdout.strip()


def _skip(reason: str) -> SyncResult:
    return SyncResult("skipped", reason, 2)


def sync_desktop_main(repo: Path, *, remote: str = "origin", branch: str = "main") -> SyncResult:
    repo = repo.expanduser()
    if not repo.exists():
        return _skip(f"repo not found: {repo}")
    if _run_git(repo, ["rev-parse", "--git-dir"]).returncode != 0:
        return _skip(f"not a git repository: {repo}")

    fetch = _run_git(repo, ["fetch", remote, branch])
    if fetch.returncode != 0:
        return _skip(f"fetch failed: {(fetch.stderr or fetch.stdout).strip()}")

    remote_ref = f"{remote}/{branch}"
    if _run_git(repo, ["rev-parse", "--verify", branch]).returncode != 0:
        return _skip(f"local branch missing: {branch}")
    if _run_git(repo, ["rev-parse", "--verify", remote_ref]).returncode != 0:
        return _skip(f"remote branch missing: {remote_ref}")

    local_sha = _git_stdout(repo, ["rev-parse", branch])
    remote_sha = _git_stdout(repo, ["rev-parse", remote_ref])
    if local_sha == remote_sha:
        return SyncResult("ok", f"{branch} already matches {remote_ref}", 0)

    ancestor = _run_git(repo, ["merge-base", "--is-ancestor", branch, remote_ref])
    if ancestor.returncode != 0:
        return _skip(f"{branch} is not an ancestor of {remote_ref}; refusing non-ff sync")

    current_branch = _git_stdout(repo, ["branch", "--show-current"])
    if current_branch == branch:
        dirty = _git_stdout(repo, ["status", "--porcelain"])
        if dirty:
            return _skip(f"{repo} has local changes on {branch}; refusing pull")
        merge = _run_git(repo, ["merge", "--ff-only", remote_ref])
        if merge.returncode != 0:
            return _skip(f"ff merge failed: {(merge.stderr or merge.stdout).strip()}")
        return SyncResult("synced", f"{branch} fast-forwarded to {remote_ref}", 0)

    update = _run_git(repo, ["branch", "--force", branch, remote_ref])
    if update.returncode != 0:
        return _skip(f"branch update failed: {(update.stderr or update.stdout).strip()}")
    return SyncResult("synced", f"{branch} ref fast-forwarded to {remote_ref}", 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast-forward the Desktop checkout main to origin/main.")
    parser.add_argument("--repo", default=str(DEFAULT_REPO), help="Canonical Desktop checkout path.")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = sync_desktop_main(Path(args.repo), remote=args.remote, branch=args.branch)
    except Exception as exc:
        print(f"[desktop-main-sync] skipped: {exc}", file=sys.stderr)
        return 2
    stream = sys.stderr if result.exit_code else sys.stdout
    print(f"[desktop-main-sync] {result.status}: {result.reason}", file=stream)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
