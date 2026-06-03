# Plan: T-2026-0003 Desktop Main Auto Sync After Auto-Ship Merge

- Status: done
- Owner role: Implementer
- Related task: `tasks/queue.md::T-2026-0003`
- Related issue / PR: [#1482](https://github.com/hskim-solv/BidMate-DocAgent/issues/1482) / [#1483](https://github.com/hskim-solv/BidMate-DocAgent/pull/1483); refresh issue #2087
- Related ADR: N/A - developer tooling only
- Created: 2026-05-25
- Last updated: 2026-06-04

## Problem Statement

After auto-ship merges a PR, the canonical Desktop checkout can remain behind
GitHub `main`. That stale main causes follow-up worktrees to start from an old
base unless the operator remembers a manual `git pull --ff-only`.

## Desired Behavior

Auto-ship Stage 5 runs a fail-soft fast-forward sync for
`/Users/hskim/Desktop/projects/BidMate-DocAgent` immediately after a successful
merge. The sync never resets or discards local work.

## Constraints

- Only fast-forward `main`.
- Skip when the target repo is missing, dirty, or divergent.
- Do not block a successful merge if the Desktop sync cannot run safely.
- Keep this as developer tooling; no eval or runtime behavior changes.

## Validation Strategy

```bash
python3 -m pytest tests/test_sync_desktop_main.py -q
python3 -m py_compile scripts/sync_desktop_main.py
git diff --check
```

## Reviewer Notes

Attack safety first: this must not run `reset`, discard local changes, or make
merge success depend on a local Desktop checkout.
