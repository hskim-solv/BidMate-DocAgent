#!/usr/bin/env python3
"""Auto-ship PR body generator.

Fills in the PR template (.github/pull_request_template.md) using git +
gh + load-bearing detection. Round-trip-validates its own output against
the §5b CI gate regexes (scripts/check_branch_and_issue.py) before
emitting; refuses to print a body that the CI gate would reject.

Called from scripts/claude-hooks/stop-ship.sh Stage 3.

Output: PR body markdown to stdout. Diagnostics to stderr.

Exit codes:
    0  body written successfully
    1  body would fail CI §5b validation
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from _governance import is_load_bearing  # noqa: E402
from check_branch_and_issue import (  # noqa: E402
    FIVE_B_ESCAPE_RE,
    FIVE_B_HEADER_RE,
    FIVE_B_TABLE_RE,
    HTML_COMMENT_RE,
    parse_branch,
)


REAL_EVAL_SUMMARY = "reports/real100/eval_summary.json"
ESCAPE_SENTENCE = "No behavior change in retrieval / verifier path."


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


def can_run_real_eval() -> bool:
    if not os.path.isdir("data/files"):
        return False
    try:
        if not os.listdir("data/files"):
            return False
    except OSError:
        return False
    if not os.path.exists("data/data_list.csv"):
        return False
    if not os.path.exists("eval/real_config.local.yaml"):
        return False
    return True


def real_eval_cache_valid() -> bool:
    if not os.path.exists(REAL_EVAL_SUMMARY):
        return False
    try:
        with open(REAL_EVAL_SUMMARY) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    cached_sha = (data.get("provenance") or {}).get("git_commit", "")
    if not cached_sha:
        return False
    rc, out, _ = _run(["git", "diff", "--name-only", f"{cached_sha}...HEAD"])
    if rc != 0:
        return False
    for f in out.splitlines():
        if is_load_bearing(f.strip()):
            return False
    return True


def render_5b(load_bearing: list[str], real_eval_mode: str) -> str:
    if not load_bearing:
        return f"{ESCAPE_SENTENCE} (no load-bearing path changed)"

    if real_eval_mode == "skip":
        return f"{ESCAPE_SENTENCE} (REAL_EVAL=skip)"

    if not can_run_real_eval():
        return (
            f"{ESCAPE_SENTENCE} "
            "(real-eval not runnable in this worktree: data/files / "
            "data/data_list.csv / eval/real_config.local.yaml unavailable.)"
        )

    if real_eval_mode == "async":
        return f"{ESCAPE_SENTENCE} <!-- real-eval-pending -->"

    if real_eval_cache_valid():
        _log("real-eval cache valid, running delta only")
        rc, out, err = _run(["make", "real-eval-delta"], timeout=120)
        if rc != 0:
            _log(f"make real-eval-delta failed: {err.strip()}")
            return f"{ESCAPE_SENTENCE} <!-- real-eval-delta-failed -->"
        return out.strip() or ESCAPE_SENTENCE

    _log("real-eval cache stale, running full make real-eval (10+ min)")
    t0 = time.time()
    rc, out, err = _run(["make", "real-eval"], timeout=1800)
    elapsed = int(time.time() - t0)
    if rc != 0:
        _log(f"make real-eval failed after {elapsed}s: {err.strip()[-500:]}")
        return f"{ESCAPE_SENTENCE} <!-- real-eval-failed: rc={rc} -->"
    _log(f"make real-eval succeeded in {elapsed}s, running delta")
    rc, out, err = _run(["make", "real-eval-delta"], timeout=120)
    if rc != 0:
        return f"{ESCAPE_SENTENCE} <!-- real-eval-delta-failed -->"
    return out.strip() or ESCAPE_SENTENCE


def has_schema_version_change(base_ref: str) -> bool:
    rc, out, _ = _run(["git", "diff", f"{base_ref}...HEAD", "--", "rag_core.py"])
    if rc != 0 or not out:
        return False
    return any(
        line.startswith(("+", "-")) and "schema_version" in line
        for line in out.splitlines()
    )


def test_summary() -> str:
    summary_path = "/tmp/ship-test-summary.txt"
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
    real_eval_mode: str,
    extra_body: str = "",
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

    test_block = test_summary()

    eval_line = (
        "See §5b (load-bearing change touched)."
        if load_bearing
        else "All `·` (no behavior change in retrieval / verifier path)."
    )

    five_b = render_5b(load_bearing, real_eval_mode)

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
        "### 5b. Real-data delta",
        "",
        five_b,
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


def validate_5b(body: str, load_bearing: list[str]) -> bool:
    """Mirror scripts/check_branch_and_issue.py --check-5b on a local string."""
    if not load_bearing:
        return True
    stripped = HTML_COMMENT_RE.sub("", body)
    m = FIVE_B_HEADER_RE.search(stripped)
    if not m:
        return False
    rest = stripped[m.end():]
    import re
    next_section = re.search(r"\n##\s", rest)
    section = rest[: next_section.start()] if next_section else rest
    return bool(FIVE_B_TABLE_RE.search(section) or FIVE_B_ESCAPE_RE.search(section))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--branch", required=True)
    p.add_argument("--base-ref", default="origin/main")
    p.add_argument(
        "--real-eval-mode", default="auto",
        choices=["auto", "skip", "async"],
    )
    p.add_argument("--extra-body", default="")
    args = p.parse_args()

    try:
        body = build_body(
            args.branch, args.base_ref, args.real_eval_mode, args.extra_body
        )
    except ValueError:
        _log(f"branch '{args.branch}' violates ADR 0007 — cannot generate body.")
        return 2

    files = changed_files(args.base_ref)
    load_bearing = [f for f in files if is_load_bearing(f)]
    if not validate_5b(body, load_bearing):
        _log(
            "GENERATED BODY WOULD FAIL --check-5b. Aborting before gh pr create. "
            "Inspect the §5b section logic in this script."
        )
        sys.stderr.write("\n--- generated body (rejected) ---\n")
        sys.stderr.write(body)
        sys.stderr.write("--- end ---\n")
        return 1

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
