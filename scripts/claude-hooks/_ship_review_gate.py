#!/usr/bin/env python3
"""Block auto-merge when PR review feedback still needs attention.

`gh pr checks --watch` only answers the CI question. This gate answers the
review question before Stage 5 merge: is the PR open, non-draft, free of
requested changes, and free of unresolved non-outdated review threads?
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Sequence


GRAPHQL_REVIEW_THREADS = r"""
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          isResolved
          isOutdated
          comments(first: 20) {
            nodes {
              path
              line
              body
              url
              author {
                login
              }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class ThreadSummary:
    path: str
    line: int | None
    author: str
    url: str
    body: str


def run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=check,
        capture_output=True,
        text=True,
    )


def resolve_pr_number(pr: str | None) -> int:
    if pr:
        return int(pr)
    out = run(["gh", "pr", "view", "--json", "number", "--jq", ".number"]).stdout.strip()
    return int(out)


def resolve_repo(repo: str | None) -> tuple[str, str, str]:
    if repo:
        owner, name = repo.split("/", 1)
        return repo, owner, name
    full = run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).stdout.strip()
    owner, name = full.split("/", 1)
    return full, owner, name


def pr_view(pr_number: int, repo_full_name: str) -> dict[str, Any]:
    raw = run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo_full_name,
            "--json",
            "state,isDraft,reviewDecision,url",
        ]
    ).stdout
    return json.loads(raw)


def fetch_unresolved_threads(owner: str, repo: str, pr_number: int) -> list[ThreadSummary]:
    cursor: str | None = None
    unresolved: list[ThreadSummary] = []
    while True:
        cmd = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL_REVIEW_THREADS}",
            "-F",
            f"owner={owner}",
            "-F",
            f"repo={repo}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor:
            cmd.extend(["-F", f"cursor={cursor}"])
        payload = json.loads(run(cmd).stdout)
        threads = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in threads["nodes"]:
            if node.get("isResolved") or node.get("isOutdated"):
                continue
            comments = node.get("comments", {}).get("nodes", [])
            if not comments:
                continue
            last = comments[-1]
            unresolved.append(
                ThreadSummary(
                    path=last.get("path") or "(unknown path)",
                    line=last.get("line"),
                    author=(last.get("author") or {}).get("login") or "(unknown)",
                    url=last.get("url") or "",
                    body=(last.get("body") or "").replace("\n", " ")[:160],
                )
            )
        page_info = threads["pageInfo"]
        if not page_info["hasNextPage"]:
            return unresolved
        cursor = page_info["endCursor"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", help="PR number; defaults to current branch PR")
    parser.add_argument("--repo", help="owner/name; defaults to `gh repo view`")
    parser.add_argument(
        "--allow-unresolved-threads",
        action="store_true",
        help="Only block CHANGES_REQUESTED, not unresolved review threads",
    )
    args = parser.parse_args()

    pr_number = resolve_pr_number(args.pr)
    repo_full_name, owner, repo = resolve_repo(args.repo)
    info = pr_view(pr_number, repo_full_name)

    blockers: list[str] = []
    if info["state"] != "OPEN":
        blockers.append(f"PR state is {info['state']}, expected OPEN")
    if info["isDraft"]:
        blockers.append("PR is draft")
    if info.get("reviewDecision") == "CHANGES_REQUESTED":
        blockers.append("reviewDecision is CHANGES_REQUESTED")

    unresolved: list[ThreadSummary] = []
    if not args.allow_unresolved_threads:
        unresolved = fetch_unresolved_threads(owner, repo, pr_number)
        if unresolved:
            blockers.append(f"{len(unresolved)} unresolved review thread(s)")

    if blockers:
        sys.stderr.write(f"ship-review-gate: blocked PR #{pr_number} ({info['url']})\n")
        for blocker in blockers:
            sys.stderr.write(f"- {blocker}\n")
        for thread in unresolved[:10]:
            location = f"{thread.path}:{thread.line}" if thread.line else thread.path
            suffix = f" — {thread.url}" if thread.url else ""
            sys.stderr.write(f"- unresolved: {location} by {thread.author}: {thread.body}{suffix}\n")
        if len(unresolved) > 10:
            sys.stderr.write(f"- ... {len(unresolved) - 10} more unresolved thread(s)\n")
        if info.get("isDraft"):
            sys.stderr.write(
                "- next safe command: "
                f"python3 scripts/agent_loop.py human-gated-exec --action pr-ready --pr {pr_number} "
                "--confirm-human-approved\n"
            )
            sys.stderr.write("- then re-arm ready mode: make ship-arm DRAFT=false\n")
        return 1

    sys.stdout.write(f"ship-review-gate: PR #{pr_number} has no review blockers.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            "ship-review-gate: gh command failed; fail closed before merge.\n"
            f"command: {' '.join(exc.cmd)}\n"
            f"stderr: {exc.stderr}\n"
        )
        sys.exit(2)
