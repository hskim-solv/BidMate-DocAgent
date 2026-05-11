#!/usr/bin/env python3
"""Validate branch naming convention and PR-issue linkage (ADR 0007).

Single source of truth for the regex. Called from two places:

- `.githooks/pre-push` (local) → `--branch <name> --check-issue`
- `.github/workflows/branch-and-issue-check.yml` (CI) → `--pr <number>`

Exit codes:
    0  ok (or exempt)
    1  convention violation (printed to stderr)
    2  internal error (e.g. `gh` unavailable in --pr mode)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Optional


BRANCH_REGEX = re.compile(
    r"^(?:feat|fix|docs|chore|refactor|test|ci|perf|build|style)"
    r"/issue-(\d+)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$"
)

EXEMPT_REGEX = re.compile(r"^(?:revert-|dependabot/|renovate/|pre-commit-ci/)")

CLOSES_REGEX = re.compile(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)\b")

ALLOWED_PREFIXES = "feat, fix, docs, chore, refactor, test, ci, perf, build, style"


def _err(msg: str) -> None:
    sys.stderr.write(msg)
    if not msg.endswith("\n"):
        sys.stderr.write("\n")


def _branch_violation_msg(branch: str) -> str:
    return (
        f"\n❌ Branch name '{branch}' violates the convention (ADR 0007).\n"
        f"   Required: <type>/issue-<N>[-<kebab-slug>]\n"
        f"   Allowed types: {ALLOWED_PREFIXES}.\n"
        f"   Examples: feat/issue-79-senior-positioning, fix/issue-104.\n"
        f"   Rename: git branch -m <new-name>\n"
        f"   See docs/adr/0007-issue-linked-branch-naming.md\n"
    )


def parse_branch(branch: str) -> Optional[int]:
    """Return the issue number if the branch matches the convention.

    Returns None if the branch is in the exempt list (bot / revert
    branches that never have a corresponding issue).
    Raises ValueError if the branch is non-exempt and non-matching;
    the caller decides how to report this.
    """
    if EXEMPT_REGEX.match(branch):
        return None
    m = BRANCH_REGEX.match(branch)
    if not m:
        raise ValueError(branch)
    return int(m.group(1))


def gh_available() -> bool:
    try:
        subprocess.run(
            ["gh", "--version"], capture_output=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_repo_slug() -> Optional[str]:
    """Determine the GitHub repo slug (owner/name) from env or `gh`."""
    if r := os.environ.get("GITHUB_REPOSITORY"):
        return r
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner",
             "-q", ".nameWithOwner"],
            capture_output=True, text=True, check=True,
        )
        slug = result.stdout.strip()
        return slug or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def issue_exists(repo: str, n: int) -> bool:
    """Return True if issue (or PR — same numbering space) N exists in repo."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{n}"],
        capture_output=True,
    )
    return result.returncode == 0


def check_branch_mode(branch: str, check_issue: bool) -> int:
    try:
        issue_n = parse_branch(branch)
    except ValueError:
        _err(_branch_violation_msg(branch))
        return 1
    if issue_n is None:
        return 0
    if not check_issue:
        return 0
    if not gh_available():
        _err(
            "ℹ️  `gh` CLI not installed — skipping issue-existence check locally.\n"
            "    CI will still verify the issue exists.\n"
        )
        return 0
    repo = get_repo_slug()
    if not repo:
        _err("ℹ️  Could not determine repo slug — skipping issue-existence check.\n")
        return 0
    if not issue_exists(repo, issue_n):
        _err(
            f"\n❌ Branch references issue #{issue_n}, but that issue does not exist in {repo}.\n"
            f"   Open one at https://github.com/{repo}/issues/new/choose\n"
            f"   or rename the branch to reference an existing issue.\n"
        )
        return 1
    return 0


def check_pr_mode(pr_number: int) -> int:
    if not gh_available():
        _err("❌ `gh` CLI is required in --pr mode but is not available.\n")
        return 2
    repo = get_repo_slug()
    if not repo:
        _err("❌ Could not determine repo slug (set GITHUB_REPOSITORY).\n")
        return 2
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "headRefName,body,number"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        _err(f"❌ Could not fetch PR #{pr_number}: {e.stderr}\n")
        return 2
    pr = json.loads(result.stdout)
    branch = pr["headRefName"]
    body = pr.get("body") or ""

    try:
        issue_n = parse_branch(branch)
    except ValueError:
        _err(_branch_violation_msg(branch))
        return 1
    if issue_n is None:
        sys.stdout.write(
            f"Branch '{branch}' is exempt from the convention check (bot / revert).\n"
        )
        return 0
    if not issue_exists(repo, issue_n):
        _err(
            f"\n❌ Branch '{branch}' references issue #{issue_n}, "
            f"but that issue does not exist in {repo}.\n"
            f"   Open one at https://github.com/{repo}/issues/new/choose\n"
            f"   or rename the branch to reference an existing issue.\n"
        )
        return 1
    matches = CLOSES_REGEX.findall(body)
    if not matches:
        _err(
            f"\n❌ PR body must contain `Closes #{issue_n}` (or `Fixes` / `Resolves`).\n"
            f"   The branch references issue #{issue_n}; the PR body must record\n"
            f"   the linkage too so GitHub auto-closes the issue on merge.\n"
        )
        return 1
    if str(issue_n) not in matches:
        joined = ", #".join(matches)
        _err(
            f"\n❌ PR body has Closes #{joined} but branch references issue #{issue_n}.\n"
            f"   At least one Closes/Fixes/Resolves must match the branch's issue number.\n"
        )
        return 1
    sys.stdout.write(
        f"OK: branch '{branch}' references issue #{issue_n}; "
        f"PR body has matching Closes link.\n"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Validate branch + issue convention (ADR 0007).",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--branch", help="Branch name to validate (local mode).")
    g.add_argument("--pr", type=int, help="PR number to validate (CI mode).")
    p.add_argument(
        "--check-issue", action="store_true",
        help="In --branch mode, also verify the referenced issue exists via gh.",
    )
    args = p.parse_args()

    if args.branch is not None:
        return check_branch_mode(args.branch, args.check_issue)
    return check_pr_mode(args.pr)


if __name__ == "__main__":
    sys.exit(main())
