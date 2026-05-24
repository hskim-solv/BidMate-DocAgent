#!/usr/bin/env python3
"""Create an issue-linked shipping branch.

This is the deterministic front door for the repo's auto-ship flow:

    make ship-start TITLE="..." TYPE=docs

It creates a GitHub issue, derives an ADR 0007-compliant branch name, fetches
``origin/main``, and switches to the new branch. The script intentionally
refuses to run with a dirty worktree because it is meant to happen before
editing starts.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Sequence


ALLOWED_TYPES = {
    "feat",
    "fix",
    "docs",
    "chore",
    "refactor",
    "test",
    "eval",
    "ci",
    "perf",
    "build",
    "style",
}
ISSUE_URL_RE = re.compile(r"/issues/(\d+)(?:\b|$)")


def run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=check,
        capture_output=True,
        text=True,
    )


def slugify(text: str, *, max_chars: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) <= max_chars:
        return slug or "work"
    trimmed = slug[:max_chars].rstrip("-")
    return trimmed or "work"


def ensure_clean_worktree() -> None:
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        raise SystemExit(
            "ship-start: refuse — worktree is dirty. Run this before editing "
            "or commit/stash the existing changes first."
        )


def create_issue(title: str, body: str, labels: str | None) -> tuple[int, str]:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    if labels:
        cmd.extend(["--label", labels])
    url = run(cmd).stdout.strip()
    m = ISSUE_URL_RE.search(url)
    if not m:
        raise SystemExit(f"ship-start: could not parse issue number from gh output: {url!r}")
    return int(m.group(1)), url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="GitHub issue title")
    parser.add_argument("--body", default="", help="GitHub issue body")
    parser.add_argument("--type", default="chore", choices=sorted(ALLOWED_TYPES))
    parser.add_argument("--slug", default="", help="Branch slug; defaults to title slug")
    parser.add_argument("--labels", default="", help="Comma-separated GitHub labels")
    parser.add_argument("--base", default="origin/main", help="Base ref for the new branch")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not fetch origin/main before creating the branch",
    )
    args = parser.parse_args()

    ensure_clean_worktree()

    body = args.body.strip()
    if not body:
        body = (
            "Created by `make ship-start`.\n\n"
            "## Acceptance criteria\n\n"
            "- Shipping branch follows ADR 0007.\n"
            "- PR closes this issue.\n"
        )

    issue_number, issue_url = create_issue(args.title, body, args.labels or None)
    slug = slugify(args.slug or args.title)
    branch = f"{args.type}/issue-{issue_number}-{slug}"

    if not args.no_fetch:
        run(["git", "fetch", "origin", "main"])
    run(["git", "switch", "-c", branch, args.base])

    sys.stdout.write(
        f"ship-start: created {issue_url}\n"
        f"ship-start: switched to {branch}\n"
        "Next: edit files, run focused tests, then `make ship-arm`.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
