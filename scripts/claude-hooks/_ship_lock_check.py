#!/usr/bin/env python3
"""Auto-ship multi-agent lock-zone enforcement.

Source of truth for the owner map: docs/multi-agent-ownership.md.
This file hardcodes the (file -> owner-issue) map because that doc is
human prose, not machine-readable. Update both when ownership changes.

Called from scripts/claude-hooks/stop-ship.sh Stage 1 before commit.

Exit codes:
    0  ok (no cross-owner edit, or current branch's issue owns the edit)
    1  cross-owner violation (printed to stderr with bypass instructions)
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from check_branch_and_issue import parse_branch  # noqa: E402


# (path -> owner issue number). Directories end with "/".
# Source: docs/multi-agent-ownership.md.
OWNER_MAP: dict[str, int] = {
    "rag_core.py": 238,
    "ingestion.py": 239,
    "visual_ingestion.py": 239,
    "rag_normalize.py": 239,
    "text_normalize.py": 239,
    "rag_synthesis.py": 240,
    "eval/": 241,
    "scripts/run_real_eval_delta.py": 241,
    "scripts/compare_eval.py": 241,
    "scripts/compare_external_baselines.py": 241,
    "scripts/leaderboard.py": 241,
    "scripts/update_readme_metrics.py": 241,
    "scripts/write_real_eval_baseline.py": 241,
    "scripts/write_synthetic_history.py": 241,
    "rag_observability.py": 242,
    "api/": 243,
    "app.py": 243,
    "demo/": 243,
    ".github/workflows/": 244,
    ".githooks/": 244,
    "scripts/check_branch_and_issue.py": 244,
    ".github/pull_request_template.md": 244,
    ".github/ISSUE_TEMPLATE/": 244,
    ".claude/settings.json": 244,
}


def owner_of(path: str) -> int | None:
    """Return the owning issue number for `path`, or None if unowned."""
    if not path:
        return None
    p = path[2:] if path.startswith("./") else path
    for entry, owner in OWNER_MAP.items():
        if entry.endswith("/"):
            if p == entry.rstrip("/") or p.startswith(entry):
                return owner
        else:
            if p == entry:
                return owner
    return None


def _check(branch: str, files: list[str]) -> int:
    try:
        branch_issue = parse_branch(branch)
    except ValueError:
        sys.stderr.write(
            f"❌ ship-lock: branch '{branch}' violates ADR 0007 — cannot determine owner.\n"
        )
        return 1
    if branch_issue is None:
        return 0

    violations: list[tuple[str, int]] = []
    for f in files:
        owner = owner_of(f)
        if owner is not None and owner != branch_issue:
            violations.append((f, owner))

    if not violations:
        return 0

    if os.environ.get("CROSS_OWNER") == "ack":
        sys.stderr.write(
            f"⚠️  ship-lock: cross-owner edits acknowledged via CROSS_OWNER=ack.\n"
        )
        for path, owner in violations:
            sys.stderr.write(f"     - {path} (owned by #{owner})\n")
        return 0

    sys.stderr.write(
        f"\n❌ ship-lock: branch is for issue #{branch_issue} but the diff\n"
        f"   touches files owned by other agents (docs/multi-agent-ownership.md):\n\n"
    )
    for path, owner in violations:
        sys.stderr.write(f"     - {path} (owner: #{owner})\n")
    sys.stderr.write(
        "\n   Either rebase the cross-owner edit behind a lightweight PR\n"
        "   from the owning issue, or bypass with: make ship-arm CROSS_OWNER=ack\n"
        "   (the bypass is logged to .claude/.ship-history.log).\n"
    )
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--branch", required=True, help="Current branch name.")
    p.add_argument(
        "--files-stdin", action="store_true",
        help="Read newline-delimited paths from stdin.",
    )
    args = p.parse_args()

    if not args.files_stdin:
        sys.stderr.write("ship-lock: --files-stdin is required.\n")
        return 2

    files = [line.strip() for line in sys.stdin if line.strip()]
    return _check(args.branch, files)


if __name__ == "__main__":
    sys.exit(main())
