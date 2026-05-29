#!/usr/bin/env python3
"""Auto-ship PR body generator.

Fills in the PR template (.github/pull_request_template.md) using git +
gh + load-bearing detection.

Called from scripts/claude-hooks/stop-ship.sh Stage 3.

Output: PR body markdown to stdout. Diagnostics to stderr.

(The §5b real-data-delta cascade and its round-trip CI validation were
deprecated in ADR 0084. The `make real-eval-delta` measurement tool is
retained, but the PR body no longer carries a required §5b section.)

Exit codes:
    0  body written successfully
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from _governance import is_load_bearing  # noqa: E402
from check_branch_and_issue import parse_branch  # noqa: E402


def _log(msg: str) -> None:
    sys.stderr.write(f"[ship:pr-body] {msg}\n")


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def changed_files(base_ref: str) -> list[str]:
    rc, out, err = _run(["git", "diff", "--name-only", f"{base_ref}...HEAD"])
    if rc != 0:
        _log(f"git diff failed: {err.strip()}")
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def commit_subject(base_ref: str) -> str:
    rc, out, _ = _run(["git", "log", "-1", "--format=%s", "HEAD"])
    return out.strip() if rc == 0 else ""


def commit_body(base_ref: str) -> str:
    rc, out, _ = _run(
        ["git", "log", f"{base_ref}..HEAD", "--reverse", "--format=%B%n---"],
    )
    if rc != 0:
        return ""
    chunks = [c.strip() for c in out.split("\n---\n") if c.strip()]
    return "\n\n".join(chunks)


def issue_title(issue_n: int) -> Optional[str]:
    rc, out, _ = _run(
        ["gh", "issue", "view", str(issue_n), "--json", "title", "--jq", ".title"],
    )
    if rc != 0:
        return None
    return out.strip() or None


def has_schema_version_change(base_ref: str) -> bool:
    rc, out, _ = _run(["git", "diff", f"{base_ref}...HEAD", "--", "rag_core.py"])
    if rc != 0 or not out:
        return False
    return any(
        line.startswith(("+", "-")) and "schema_version" in line
        for line in out.splitlines()
    )


def test_summary(summary_path: str | None) -> str:
    # The dispatcher (stop-ship.sh) writes the local test output to a
    # worktree-unique mktemp file (#571) and passes the path here. A fixed
    # global path would let a concurrent worktree's stale file leak in as a
    # false success signal (issue #1274).
    if not summary_path:
        return "Local test run not captured by dispatcher."
    if not os.path.exists(summary_path):
        return "Local test run not captured by dispatcher."
    try:
        with open(summary_path) as f:
            return f.read().strip() or "Local tests ran (empty output)."
    except OSError:
        return "Local test summary unreadable."


def build_body(
    branch: str,
    base_ref: str,
    extra_body: str = "",
    test_summary_path: str | None = None,
) -> str:
    issue_n = parse_branch(branch)
    files = changed_files(base_ref)
    load_bearing = [f for f in files if is_load_bearing(f)]
    body_para = (commit_body(base_ref) or commit_subject(base_ref) or
                 f"Implements work for issue #{issue_n}.")

    files_block = "\n".join(
        f"- `{f}`" + (" (load-bearing)" if is_load_bearing(f) else "")
        for f in files
    ) or "- (no file changes detected)"

    risk_line = (
        "Auto-generated PR. Test coverage: see §4. Reviewer should focus on "
        f"the {len(load_bearing)} load-bearing path(s) listed above."
        if load_bearing
        else "Auto-generated PR; no load-bearing paths changed."
    )

    test_block = test_summary(test_summary_path)

    # ADR 0084 deprecated the §5b gate. For load-bearing changes we still note
    # the recommended (no longer gated) real-data evidence path; for everything
    # else the eval impact is the usual "no behavior change" line.
    eval_line = (
        "Load-bearing path touched. Recommended (not gated, ADR 0084): note "
        "real-data impact (behavior change + evidence aggregate) or state no behavior change."
        if load_bearing
        else "All `·` (no behavior change in retrieval / verifier path)."
    )

    bc_line = (
        "schema_version bumped (detected in diff)."
        if has_schema_version_change(base_ref)
        else "No public-API change detected."
    )

    sections = [
        "## 1. What changed and why",
        "",
        body_para,
        "",
        f"Closes #{issue_n}",
        "",
        "## 2. Files affected",
        "",
        files_block,
        "",
        "## 3. Risks",
        "",
        risk_line,
        "",
        "## 4. Tests",
        "",
        test_block,
        "",
        "## 5. Eval impact",
        "",
        eval_line,
        "",
        "## 6. Backward compatibility",
        "",
        bc_line,
        "",
        "## 7. Out of scope",
        "",
        "N/A — single-concern auto-shipped PR.",
    ]
    if extra_body:
        sections.extend(["", "---", "", extra_body])
    return "\n".join(sections) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--branch")
    p.add_argument("--base-ref", default="origin/main")
    p.add_argument(
        # Accepted for backward compatibility with stop-ship.sh's invocation,
        # but ignored: the §5b real-data-delta cascade was deprecated (ADR 0084).
        "--real-eval-mode", default="auto",
        choices=["auto", "skip", "async"],
        help="Deprecated no-op (ADR 0084); accepted for stop-ship.sh compat.",
    )
    p.add_argument("--extra-body", default="")
    p.add_argument(
        "--test-summary-path", metavar="PATH", default=None,
        help="Path the dispatcher wrote local test output to (worktree-unique "
             "mktemp, #1274). Omit for a 'not captured' note.",
    )
    args = p.parse_args()

    if not args.branch:
        p.error("--branch is required")

    try:
        body = build_body(
            args.branch, args.base_ref, args.extra_body,
            args.test_summary_path,
        )
    except ValueError:
        _log(f"branch '{args.branch}' violates ADR 0007 — cannot generate body.")
        return 2

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
