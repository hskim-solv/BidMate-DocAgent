# Plan: T-2026-0016 Agent worktree overlap preflight

- Status: review
- Owner role: Maintainer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0016`
- Related issue / PR: Issue #1541 / PR TBD
- Related ADR: ADR 0007; ADR 0079
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

Codex sessions can start from stale detached worktrees or duplicate an issue that
another worktree, branch, or PR already owns. The existing `preflight` command
checks handoff, surface, and validation, but it does not prove that starting the
work is non-overlapping.

## Desired Behavior

Before editing files, an agent can run a read-only overlap preflight for a target
issue and ADR 0007 branch. It should block duplicate or stale starts and write a
local report under `reports/agent_loop/`.

## Constraints

- Report-only command; no tracked file, branch, PR, issue, or remote mutation.
- Fail closed when GitHub issue or PR state cannot be read.
- Treat detached or stale checkout state as a blocker.
- Treat remote branch leftovers as warnings unless an open/merged PR proves the
  work is active or completed.

## Implementation Summary

1. Add `overlap-preflight` to `scripts/agent_loop.py`.
2. Inspect `git worktree list --porcelain`, local issue branches, remote heads,
   open PRs, branch PR history, issue state, current branch, and `origin/main`
   freshness.
3. Return `blocked`, `warn`, or `clear` and render Markdown plus optional JSON.
4. Add regression tests for duplicate worktree, open PR, closed/merged history,
   detached/stale checkout, and clear state.
5. Document start-of-task usage in `tasks/README.md` and
   `docs/operations/ai-codex-workflow.md`.

## Acceptance Criteria

- [x] Same issue branch in another worktree blocks.
- [x] Same issue open PR blocks.
- [x] Closed issue with merged branch history blocks as completed.
- [x] Detached or stale current checkout blocks.
- [x] Clean ADR 0007 branch/issue with no overlap reports clear.
- [x] Start-of-task docs mention overlap preflight.

## Validation

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 -m py_compile scripts/agent_loop.py
python3 scripts/agent_loop.py overlap-preflight --issue 1541 --branch chore/issue-1541-overlap-preflight
python3 scripts/check_doc_links.py --check-all --paths tasks/README.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md tasks/queue.md
git diff --check
make check-branch
```

## Reviewer Notes

Focus on false-clear risk: if the command cannot prove issue, PR, worktree, or
freshness state, it should block or warn instead of returning clear. Also verify
that the command writes only ignored report artifacts.

