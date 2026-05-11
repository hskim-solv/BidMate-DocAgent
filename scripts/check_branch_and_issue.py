#!/usr/bin/env python3
"""Validate branch naming convention, PR-issue linkage, and §5b real-data delta.

Single source of truth for the regexes. Called from three places:

- `.githooks/pre-push` (local) → `--branch <name> --check-issue`
- `.github/workflows/branch-and-issue-check.yml` (CI) → `--pr <number>`
- Same CI workflow → `--check-5b <number>` (enforces PR template §5b for
  load-bearing changes, per CLAUDE.md PR #69 lesson)

Exit codes:
    0  ok (or exempt)
    1  convention violation (printed to stderr)
    2  internal error (e.g. `gh` unavailable)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Optional

from _governance import is_load_bearing


BRANCH_REGEX = re.compile(
    r"^(?:feat|fix|docs|chore|refactor|test|ci|perf|build|style)"
    r"/issue-(\d+)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$"
)

EXEMPT_REGEX = re.compile(r"^(?:revert-|dependabot/|renovate/|pre-commit-ci/)")

CLOSES_REGEX = re.compile(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)\b")

ALLOWED_PREFIXES = "feat, fix, docs, chore, refactor, test, ci, perf, build, style"

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FIVE_B_HEADER_RE = re.compile(r"###\s+5b\.\s*Real-data delta", re.IGNORECASE)
FIVE_B_TABLE_RE = re.compile(r"^\s*\|.+\|.+\|", re.MULTILINE)
FIVE_B_ESCAPE_RE = re.compile(
    r"No behavior change in\s+(?:retrieval|verifier|eval|api|ingestion)\b",
    re.IGNORECASE,
)


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


def _five_b_section(body: str) -> Optional[str]:
    """Return the §5b section text (HTML comments stripped) or None if absent.

    The PR template ships with HTML comments under each header explaining
    what to write; those comments are invisible in rendered markdown and
    must not satisfy the §5b requirement. We strip them first.
    """
    stripped = HTML_COMMENT_RE.sub("", body)
    m = FIVE_B_HEADER_RE.search(stripped)
    if not m:
        return None
    rest = stripped[m.end():]
    next_section = re.search(r"\n##\s", rest)
    if next_section:
        return rest[: next_section.start()]
    return rest


def check_5b_mode(pr_number: int) -> int:
    """Verify PR body §5b for load-bearing changes.

    Logic:
      1. `gh pr view --json files,body` → list of changed paths + body text.
      2. Filter changed paths through `_governance.is_load_bearing()`.
      3. If none match → exit 0 (skip; non-load-bearing PR).
      4. If any match → require body to contain the '### 5b. Real-data delta'
         header AND, beneath it (HTML comments stripped), either a markdown
         table row OR the escape sentence
         'No behavior change in retrieval/verifier/eval/api/ingestion path'.
      5. On failure: print actionable error pointing to PR #69 lesson.
    """
    if not gh_available():
        _err("❌ `gh` CLI is required in --check-5b mode but is not available.\n")
        return 2
    repo = get_repo_slug()
    if not repo:
        _err("❌ Could not determine repo slug (set GITHUB_REPOSITORY).\n")
        return 2
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "files,body"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        _err(f"❌ Could not fetch PR #{pr_number}: {e.stderr}\n")
        return 2

    pr = json.loads(result.stdout)
    files = pr.get("files") or []
    body = pr.get("body") or ""

    load_bearing_hits = [
        f.get("path", "") for f in files if is_load_bearing(f.get("path", ""))
    ]
    if not load_bearing_hits:
        sys.stdout.write(
            f"OK: PR #{pr_number} changes no load-bearing path; §5b not required.\n"
        )
        return 0

    section = _five_b_section(body)
    example = load_bearing_hits[0]
    remediation = (
        "   PR #69 lesson: the synthetic CI delta alone missed an intended-abstention regression.\n"
        "   Either:\n"
        "     (a) attach the `make real-eval-delta` aggregate table under\n"
        "         '### 5b. Real-data delta', or\n"
        "     (b) state explicitly: 'No behavior change in retrieval / verifier path.'\n"
        "   See: .github/pull_request_template.md and CLAUDE.md.\n"
    )
    if section is None:
        _err(
            f"\n❌ Load-bearing change detected (e.g. {example}) but PR body has\n"
            f"   no '### 5b. Real-data delta' section.\n" + remediation
        )
        return 1

    has_table = bool(FIVE_B_TABLE_RE.search(section))
    has_escape = bool(FIVE_B_ESCAPE_RE.search(section))
    if not (has_table or has_escape):
        _err(
            f"\n❌ Load-bearing change detected (e.g. {example}) but §5b is\n"
            f"   missing both a markdown table and the escape sentence.\n"
            + remediation
        )
        return 1

    sys.stdout.write(
        f"OK: PR #{pr_number} touches load-bearing path "
        f"({example}); §5b contains "
        f"{'table' if has_table else 'escape sentence'}.\n"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Validate branch + issue convention + §5b (ADR 0007, CLAUDE.md).",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--branch", help="Branch name to validate (local mode).")
    g.add_argument("--pr", type=int, help="PR number to validate (CI mode).")
    g.add_argument(
        "--check-5b", type=int, dest="check_5b", metavar="PR_NUMBER",
        help="Verify PR body §5b for load-bearing changes (CI mode).",
    )
    p.add_argument(
        "--check-issue", action="store_true",
        help="In --branch mode, also verify the referenced issue exists via gh.",
    )
    args = p.parse_args()

    if args.branch is not None:
        return check_branch_mode(args.branch, args.check_issue)
    if args.pr is not None:
        return check_pr_mode(args.pr)
    return check_5b_mode(args.check_5b)


if __name__ == "__main__":
    sys.exit(main())
