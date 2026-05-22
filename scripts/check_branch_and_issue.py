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

from _governance import (
    ceiling_ratchet_violations,
    is_load_bearing,
    parse_allow_regression_categories,
    parse_failure_rate_ceilings,
)


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
# Accepts the §5b "no behavior change" attestation in EITHER language so the
# gate matches the (Korean-first) PR template example, not just the English
# sentinel (issue #1048 — template↔gate drift made template-following PRs fail
# CI). The Korean branch anchors "변(화|경|동)" immediately before "없(음|다|습니다)"
# (only whitespace allowed between) so a sentence asserting that behavior DID
# change cannot accidentally satisfy the escape — that false-escape is exactly
# the PR #69 regression class §5b guards against.
FIVE_B_ESCAPE_RE = re.compile(
    r"No behavior change in\s+(?:retrieval|verifier|eval|api|ingestion)\b"
    r"|"
    r"(?:검색|검증|수집|평가|retrieval|verifier|eval|api|ingestion)"
    r"[^\n]{0,16}?"
    r"(?:변화|변경|변동)\s*없(?:음|다|습니다)",
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
         table row OR the escape sentence in English ('No behavior change in
         retrieval/verifier/eval/api/ingestion path') or Korean ('검색/검증
         path 동작 변화 없음.') — see FIVE_B_ESCAPE_RE.
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
        "     (b) state explicitly, e.g. '검색/검증 path 동작 변화 없음.'\n"
        "         (English also accepted: 'No behavior change in retrieval / verifier path.')\n"
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
        "   NOTE: this gate enforces §5b *presence* only. The accuracy of the\n"
        "   numbers / truth of the attestation is the reviewer's responsibility\n"
        "   — CI green != §5b content verified (issue #1027).\n"
    )
    return 0


CEILING_TEST_PATH = "tests/test_failure_rate_regression.py"


def _fetch_file_at_ref(repo: str, path: str, ref: str) -> Optional[str]:
    """Return `path` content at `ref` via the GitHub contents API, or None.

    Uses the `raw` media type so no base64 decode is needed. Returns None on
    any failure (404 = file absent at that ref, network error, etc.) so the
    caller decides whether absence is fatal or a skip.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}",
             "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return result.stdout


def check_ceiling_ratchet_mode(pr_number: int) -> int:
    """Enforce the ADR 0062 monotone ceiling ratchet for a PR.

    The failure-rate ceilings in ``tests/test_failure_rate_regression.py`` may
    only ratchet DOWN as fixes land. The in-test guard only checks each ceiling
    against the *current committed rate*, never the base branch — so a PR could
    RAISE a ceiling (loosening the gate) with every test green. This closes that
    hole.

    Logic:
      1. `gh pr view --json files,body,baseRefName,headRefOid`.
      2. If the ceiling test file isn't in the diff → exit 0 (ceilings unchanged).
      3. Fetch the base + head versions of the file via the contents API.
      4. Diff the parsed ceilings; FAIL on any loosening (raised, or a gated
         category removed) not justified by an `[ALLOW_REGRESSION: <category>
         ...]` token in the PR body.
    """
    if not gh_available():
        _err("❌ `gh` CLI is required in --check-ceiling-ratchet mode but is not available.\n")
        return 2
    repo = get_repo_slug()
    if not repo:
        _err("❌ Could not determine repo slug (set GITHUB_REPOSITORY).\n")
        return 2
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "files,body,baseRefName,headRefOid"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        _err(f"❌ Could not fetch PR #{pr_number}: {e.stderr}\n")
        return 2

    pr = json.loads(result.stdout)
    files = pr.get("files") or []
    body = pr.get("body") or ""
    base_ref = pr.get("baseRefName") or ""
    head_ref = pr.get("headRefOid") or ""

    changed = {f.get("path", "") for f in files}
    if CEILING_TEST_PATH not in changed:
        sys.stdout.write(
            f"OK: PR #{pr_number} does not touch {CEILING_TEST_PATH}; "
            "ceiling ratchet not applicable.\n"
        )
        return 0

    base_src = _fetch_file_at_ref(repo, CEILING_TEST_PATH, base_ref) if base_ref else None
    if base_src is None:
        sys.stdout.write(
            f"OK: {CEILING_TEST_PATH} not present on base '{base_ref}' "
            "(first introduction); no ratchet baseline to compare against.\n"
        )
        return 0
    head_src = _fetch_file_at_ref(repo, CEILING_TEST_PATH, head_ref) if head_ref else None
    if head_src is None:
        _err(f"❌ Could not fetch {CEILING_TEST_PATH} at head '{head_ref}'.\n")
        return 2

    try:
        base_ceilings = parse_failure_rate_ceilings(base_src)
    except (ValueError, SyntaxError) as exc:
        # Base unparseable → don't block the PR on an upstream issue.
        sys.stdout.write(
            f"OK: could not parse ceilings on base '{base_ref}' ({exc}); "
            "skipping ratchet check.\n"
        )
        return 0
    try:
        head_ceilings = parse_failure_rate_ceilings(head_src)
    except (ValueError, SyntaxError) as exc:
        _err(
            f"\n❌ Could not parse the ratchet ceilings in {CEILING_TEST_PATH} "
            f"at this PR's head: {exc}\n"
            "   CEILING_RATE_BY_CATEGORY (dict) and CEILING_TOTAL_FAILURE_RATE\n"
            "   (float) must stay plain literals so the ADR 0062 ratchet gate can\n"
            "   read them. Keep them parseable (and update the ADR 0062\n"
            "   Verification markers if you move them).\n"
        )
        return 1

    allowed = parse_allow_regression_categories(body)
    violations = ceiling_ratchet_violations(base_ceilings, head_ceilings, allowed)
    if violations:
        _err(
            f"\n❌ ADR 0062 monotone ceiling ratchet violated by PR #{pr_number}:\n\n"
        )
        for v in violations:
            _err(f"     - {v}\n")
        _err(
            "\n   The failure-rate ceilings in tests/test_failure_rate_regression.py\n"
            "   may only ratchet DOWN as fixes land. To LOOSEN one deliberately,\n"
            "   add an explicit token to the PR body, e.g.:\n"
            "       [ALLOW_REGRESSION: retrieval_miss 0.34→0.40 reason here]\n"
            "   See docs/adr/0062-failure-rate-regression-contract.md and\n"
            "   docs/operations/failure-mode-harden-process.md.\n"
        )
        return 1

    sys.stdout.write(
        f"OK: PR #{pr_number} touches {CEILING_TEST_PATH}; "
        "no unjustified ceiling loosening.\n"
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
    g.add_argument(
        "--check-ceiling-ratchet", type=int, dest="check_ceiling_ratchet",
        metavar="PR_NUMBER",
        help="Enforce the ADR 0062 monotone failure-rate ceiling ratchet: a PR "
             "that raises/removes a ceiling in tests/test_failure_rate_regression.py "
             "without an [ALLOW_REGRESSION: <category> ...] token fails (CI mode).",
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
    if args.check_ceiling_ratchet is not None:
        return check_ceiling_ratchet_mode(args.check_ceiling_ratchet)
    return check_5b_mode(args.check_5b)


if __name__ == "__main__":
    sys.exit(main())
