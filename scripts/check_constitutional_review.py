#!/usr/bin/env python3
"""Constitutional-change gate: a code-owner (≠ PR author) must APPROVE.

Replaces the author-writable ``[constitutional-change-ack]`` PR-body marker
(ADR 0088) with a CODEOWNERS-based trusted signal the autonomous staging
self-ship loop physically cannot self-produce: GitHub blocks a PR author from
approving their own PR, so requiring a code-owner review on the constitutional
ship-lane files means the loop (= the PR author) cannot satisfy the gate alone
(ADR 0091).

Single source of truth for the protected-path set. Called by the
``staging-self-ship-guard`` workflow as the required status check:

    python scripts/check_constitutional_review.py --pr <number>

The gh-fetching is funnelled through an injectable ``gh_json`` /
``read_codeowners`` seam so the pure decision function
(``requires_owner_approval_violation``) is unit-tested without network.

Exit codes:
    0  ok (no protected file touched, or a code-owner ≠ author approved)
    1  violation (protected files touched without a non-author code-owner approval)
    2  internal error (e.g. `gh` unavailable, repo slug undeterminable)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional


# The constitutional ship-lane file set. This MUST stay in sync with
# .github/CODEOWNERS — tests/test_constitutional_review.py asserts parity so the
# two cannot drift. Paths are repo-relative with NO leading slash (matching the
# `gh api .../files` and `git diff --name-only` output format); the CODEOWNERS
# patterns carry a leading `/` (anchored) which the parity test strips.
PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "scripts/_staging_ship.py",
        "scripts/_ship_env.py",
        "scripts/_ship_payload_guard.py",
        "scripts/_governance.py",
        ".github/workflows/staging-self-ship-guard.yml",
        ".github/CODEOWNERS",
        ".githooks/pre-commit",
    }
)

CODEOWNERS_DEFAULT = ".github/CODEOWNERS"


def requires_owner_approval_violation(
    changed_files: Iterable[str],
    author_login: str,
    approved_reviewer_logins: Iterable[str],
    owner_logins: Iterable[str],
) -> Optional[str]:
    """Return an error string if the constitutional gate is violated, else None.

    A violation exists iff at least one ``PROTECTED_PATHS`` file is touched AND
    no *qualifying approver* exists. A qualifying approver is a reviewer who:

      - is in ``owner_logins`` (a CODEOWNERS-listed code owner), AND
      - is NOT the PR author (``author_login``).

    The author is excluded **even if the author is somehow an owner** — the
    autonomous loop (= the PR author) must never be able to self-approve the
    constitutional change. GitHub already blocks self-approval; this is the
    belt-and-suspenders second layer (ADR 0091).
    """
    changed = set(changed_files)
    touched = sorted(PROTECTED_PATHS & changed)
    if not touched:
        return None

    author = (author_login or "").strip()
    owners = {o.strip() for o in owner_logins if o and o.strip()}
    approvers = {r.strip() for r in approved_reviewer_logins if r and r.strip()}

    qualifying = {a for a in approvers if a in owners and a != author}
    if qualifying:
        return None

    return (
        "Constitutional ship-lane files changed without a code-owner approval: "
        f"{touched}. A review APPROVED by a CODEOWNERS code owner who is NOT the "
        f"PR author (author='{author or '?'}') is required (ADR 0091). GitHub "
        "blocks self-approval, so the autonomous loop cannot satisfy this gate "
        "alone — a human code owner must review and approve."
    )


# ---------------------------------------------------------------------------
# CODEOWNERS owner parsing.
# ---------------------------------------------------------------------------

# A CODEOWNERS data line: `<pattern> @owner [@owner ...]`. Comments (`#`) and
# blank lines are skipped. Owners are `@`-prefixed logins (user or @org/team);
# we collect the bare login (strip the leading `@`). Team refs (`@org/team`)
# are kept verbatim minus the `@` — they simply won't match an individual
# reviewer login, which is the safe (fail-closed) direction.
_CODEOWNERS_OWNER_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9._-]+)?)")


def parse_codeowners_logins(text: str) -> set[str]:
    """Return the set of all `@`-prefixed logins appearing in CODEOWNERS text.

    Robust + simple: rather than resolve which pattern matches which touched
    file (CODEOWNERS glob semantics), we treat the full set of code-owner
    logins as the owner pool. Every protected path in this repo maps to the
    same owner, so this is equivalent and avoids a glob matcher. Comment lines
    and blanks are ignored.
    """
    logins: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for m in _CODEOWNERS_OWNER_RE.finditer(line):
            logins.add(m.group(1))
    return logins


def codeowners_protected_patterns(text: str) -> set[str]:
    """Return the leading-`/`-stripped patterns from CODEOWNERS data lines.

    Used by the parity test to assert the CODEOWNERS pattern set equals
    ``PROTECTED_PATHS``. A data line is `<pattern> <owners...>`; the pattern is
    the first whitespace-delimited token. The leading `/` (path anchor) is
    stripped so the result matches the repo-relative ``PROTECTED_PATHS`` form.
    """
    patterns: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split()[0]
        patterns.add(token.lstrip("/"))
    return patterns


def read_codeowners(path: str | Path = CODEOWNERS_DEFAULT) -> str:
    """Read the CODEOWNERS file text, or "" if it is missing."""
    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# gh-fetching seam (injectable for unit tests).
# ---------------------------------------------------------------------------


def gh_available() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
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


def _gh_json(args: list[str]) -> str:
    """Run `gh <args>` and return stdout. Raises on failure."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True,
    )
    return result.stdout


def fetch_changed_files(repo: str, pr: int, gh_json: Callable[[list[str]], str]) -> list[str]:
    out = gh_json([
        "api", f"repos/{repo}/pulls/{pr}/files", "--paginate",
        "--jq", ".[].filename",
    ])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def fetch_author_login(repo: str, pr: int, gh_json: Callable[[list[str]], str]) -> str:
    out = gh_json(["api", f"repos/{repo}/pulls/{pr}", "--jq", ".user.login"])
    return out.strip()


def fetch_approved_reviewers(repo: str, pr: int, gh_json: Callable[[list[str]], str]) -> list[str]:
    out = gh_json([
        "api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate",
        "--jq", '[.[]|select(.state=="APPROVED")|.user.login]',
    ])
    # The --jq array prints one JSON array per page; flatten them.
    logins: list[str] = []
    for chunk in out.splitlines():
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            logins.extend(str(x) for x in parsed)
    return logins


def check_pr_mode(
    pr: int,
    *,
    codeowners_path: str = CODEOWNERS_DEFAULT,
    gh_json: Callable[[list[str]], str] = _gh_json,
) -> int:
    """Fetch PR metadata via gh and run the constitutional gate. Returns rc."""
    if not gh_available():
        sys.stderr.write(
            "❌ `gh` CLI is required for the constitutional review check but is "
            "not available.\n"
        )
        return 2
    repo = get_repo_slug()
    if not repo:
        sys.stderr.write(
            "❌ Could not determine repo slug (set GITHUB_REPOSITORY).\n"
        )
        return 2

    try:
        changed = fetch_changed_files(repo, pr, gh_json)
        author = fetch_author_login(repo, pr, gh_json)
        approvers = fetch_approved_reviewers(repo, pr, gh_json)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"❌ Could not fetch PR #{pr} metadata via gh: {exc.stderr or exc}\n"
        )
        return 2

    owner_logins = parse_codeowners_logins(read_codeowners(codeowners_path))

    violation = requires_owner_approval_violation(
        changed_files=changed,
        author_login=author,
        approved_reviewer_logins=approvers,
        owner_logins=owner_logins,
    )
    if violation is None:
        touched = sorted(PROTECTED_PATHS & set(changed))
        if touched:
            sys.stdout.write(
                f"OK: constitutional files {touched} changed, and a code-owner "
                f"(≠ author '{author}') has APPROVED (ADR 0091).\n"
            )
        else:
            sys.stdout.write("OK: no constitutional ship-lane files changed.\n")
        return 0

    sys.stderr.write(f"::error::{violation}\n")
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Constitutional-change gate (ADR 0091): a CODEOWNERS code owner who "
            "is NOT the PR author must APPROVE any PR touching the protected "
            "ship-lane files."
        ),
    )
    p.add_argument(
        "--pr", type=int, required=True,
        help="PR number to validate (CI mode; fetches files/author/reviews via gh).",
    )
    p.add_argument(
        "--codeowners", default=CODEOWNERS_DEFAULT,
        help="Path to the CODEOWNERS file (default: .github/CODEOWNERS).",
    )
    args = p.parse_args(argv)
    return check_pr_mode(args.pr, codeowners_path=args.codeowners)


if __name__ == "__main__":
    sys.exit(main())
