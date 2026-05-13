#!/usr/bin/env python3
"""Write `.claude/.ship-armed` from `make ship-arm`.

Centralises TTL parsing, branch capture, and JSON write in Python so the
Makefile target stays declarative.

Exit codes:
    0  armed file written
    1  refused (e.g. on main, branch violates ADR 0007)
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from check_branch_and_issue import parse_branch  # noqa: E402


ARMED_FILE = ".claude/.ship-armed"
TTL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
PROTECTED_BRANCHES = {"main", "master", "develop", "HEAD"}


def parse_ttl(ttl: str) -> timedelta:
    m = TTL_RE.match(ttl)
    if not m:
        raise ValueError(f"invalid TTL '{ttl}' (expected e.g. 30m, 2h, 1d)")
    n, unit = int(m.group(1)), m.group(2).lower()
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return timedelta(seconds=n * factor)


def current_branch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ttl", default="2h")
    p.add_argument("--real-eval", default="auto",
                   choices=["auto", "skip", "async"])
    p.add_argument("--draft", default="false")
    p.add_argument("--dry-run", default="0")
    p.add_argument("--cross-owner", default="")
    p.add_argument("--stacked", default="")
    args = p.parse_args()

    try:
        ttl = parse_ttl(args.ttl)
    except ValueError as e:
        sys.stderr.write(f"ship-arm: {e}\n")
        return 2

    branch = current_branch()
    if branch in PROTECTED_BRANCHES or branch.startswith("release/"):
        sys.stderr.write(
            f"ship-arm: refuse to arm on protected branch '{branch}'.\n"
            f"   Switch to a feature branch first.\n"
        )
        return 1

    try:
        issue = parse_branch(branch)
    except ValueError:
        sys.stderr.write(
            f"ship-arm: branch '{branch}' violates ADR 0007.\n"
            f"   Required: <type>/issue-<N>[-<slug>].\n"
        )
        return 1
    if issue is None:
        sys.stderr.write(
            f"ship-arm: branch '{branch}' is exempt (bot/revert) — refusing to ship.\n"
        )
        return 1

    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + ttl
    state = {
        "branch": branch,
        "issue": issue,
        "armed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "real_eval_mode": args.real_eval,
        "draft": args.draft,
        "dry_run": int(args.dry_run) if args.dry_run.isdigit() else 0,
        "cross_owner": args.cross_owner,
        "stacked": args.stacked,
    }
    os.makedirs(os.path.dirname(ARMED_FILE), exist_ok=True)
    with open(ARMED_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    sys.stdout.write(
        f"ship: armed for {branch} (issue #{issue})\n"
        f"      expires {expires.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"(in {args.ttl})\n"
        f"      real_eval={args.real_eval} draft={args.draft} "
        f"dry_run={state['dry_run']}\n"
    )
    if state["dry_run"]:
        sys.stdout.write(
            "      DRY_RUN=1: mutating commands will be echoed to "
            ".claude/.ship-dryrun.log only.\n"
        )
    if args.cross_owner == "ack":
        sys.stdout.write("      CROSS_OWNER=ack: multi-agent lock bypass active.\n")
    if args.stacked == "ack":
        sys.stdout.write("      STACKED=ack: heterogeneous-prefix bypass active.\n")
    sys.stdout.write(
        "      Disarm anytime with: make ship-disarm "
        "(or rm .claude/.ship-armed)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
