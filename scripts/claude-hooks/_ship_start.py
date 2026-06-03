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
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
# overlap-preflight confines its --out / --json-out under reports/agent_loop/
# (scripts/agent_loop.py::_safe_output_path), so the gate's mktemp files MUST
# live there too — a plain /tmp mktemp is rejected. Per-invocation unique names
# (mktemp, not a fixed /tmp path) avoid the multi-worktree shared-file footgun
# (memory issue #1274).
OVERLAP_REPORT_DIR = REPO_ROOT / "reports" / "agent_loop"
# Stable substring of the deterministic, gh-independent base-staleness blocker
# emitted by build_overlap_preflight. Only THIS blocker hard-blocks ship-start;
# every other blocker/warning is advisory (a fresh issue+branch cannot have an
# open PR / sibling worktree yet, and we never hard-fail on gh non-determinism).
STALE_BASE_MARKER = "does not contain origin/main"


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


def split_labels(labels: str | None) -> list[str]:
    if not labels:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in labels.split(","):
        label = raw.strip()
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def apply_issue_labels(issue_number: int, labels: list[str]) -> None:
    for label in labels:
        result = run(
            ["gh", "issue", "edit", str(issue_number), "--add-label", label],
            check=False,
        )
        if result.returncode == 0:
            continue
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        print(
            f"ship-start: warning — could not add label {label!r}{suffix}",
            file=sys.stderr,
        )


def create_issue(title: str, body: str, labels: str | None) -> tuple[int, str]:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    url = run(cmd).stdout.strip()
    m = ISSUE_URL_RE.search(url)
    if not m:
        raise SystemExit(f"ship-start: could not parse issue number from gh output: {url!r}")
    issue_number = int(m.group(1))
    apply_issue_labels(issue_number, split_labels(labels))
    return issue_number, url


def run_overlap_gate(
    issue: int,
    branch: str,
    *,
    ack: bool,
    paths: Sequence[str] | None,
) -> None:
    """Run overlap-preflight between fetch and branch creation (issue #1836).

    Policy:
      * a base-staleness blocker (local HEAD lacks origin/main) raises SystemExit
        unless ``ack`` — deterministic + gh-independent, safe to hard-block;
      * path / open-PR overlap warnings (and any other non-staleness blocker)
        print to stderr and the function returns so the branch is still created;
      * any failure to RUN the scan (non-zero exit with no staleness blocker,
        timeout, unparseable JSON, missing report) fails OPEN — overlap-preflight
        is a read-only advisory and must never hard-fail a fresh task on
        transient/offline git/gh state (memory feedback_merge_admin_gate §7).
    """
    OVERLAP_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_fd, md_path = tempfile.mkstemp(dir=str(OVERLAP_REPORT_DIR), prefix="overlap_", suffix=".md")
    os.close(md_fd)
    json_fd, json_path = tempfile.mkstemp(dir=str(OVERLAP_REPORT_DIR), prefix="overlap_", suffix=".json")
    os.close(json_fd)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "agent_loop.py"),
        "overlap-preflight",
        "--issue",
        str(issue),
        "--branch",
        branch,
        "--out",
        md_path,
        "--json-out",
        json_path,
    ]
    if paths:
        cmd.extend(["--paths", *paths])
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
        report = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ship-start: overlap-preflight could not run ({exc}); continuing (fail-open).", file=sys.stderr)
        return
    finally:
        for p in (md_path, json_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    blockers = [str(b) for b in report.get("blockers", [])]
    warnings = [str(w) for w in report.get("warnings", [])]
    stale = any(STALE_BASE_MARKER in b for b in blockers)

    for warning in warnings:
        print(f"ship-start: overlap warning — {warning}", file=sys.stderr)

    if stale and not ack:
        for b in blockers:
            print(f"ship-start: overlap blocker — {b}", file=sys.stderr)
        raise SystemExit(
            "ship-start: refuse — local HEAD does not contain origin/main (stale base). "
            "Refresh from latest main, or pass --overlap-ack / OVERLAP=ack to override."
        )
    if stale and ack:
        print("ship-start: overlap — stale base acknowledged (--overlap-ack); continuing.", file=sys.stderr)
        return
    if proc.returncode != 0 and not blockers:
        # overlap-preflight exited non-zero but recorded no blockers we can read
        # (e.g. it crashed). Diagnostic only — the function already falls through
        # to a fail-open return below rather than wedging a fresh task.
        print("ship-start: overlap-preflight exited non-zero with no blocker payload; continuing (fail-open).", file=sys.stderr)


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
    parser.add_argument(
        "--overlap-ack",
        action="store_true",
        help="Acknowledge a stale-base overlap blocker and create the branch anyway "
        "(env OVERLAP=ack has the same effect).",
    )
    parser.add_argument(
        "--no-overlap-check",
        action="store_true",
        help="Skip the overlap-preflight start-of-task gate entirely (mirrors --no-fetch).",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Repo-relative load-bearing paths to add a path-scope overlap scan "
        "(warns if another worktree/open PR touches them).",
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
    if not args.no_overlap_check:
        ack = args.overlap_ack or os.environ.get("OVERLAP", "").strip().lower() == "ack"
        run_overlap_gate(issue_number, branch, ack=ack, paths=args.paths)
    run(["git", "switch", "-c", branch, args.base])

    sys.stdout.write(
        f"ship-start: created {issue_url}\n"
        f"ship-start: switched to {branch}\n"
        "Next: edit files, run focused tests, then `make ship-arm`.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
