# Plan: T-2026-0034 Query rewrite and decomposition experiment

- Status: draft
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0034`
- Related issue / PR: N/A
- Related ADR: N/A - no decision-level change identified during backlog hydration
- Created: 2026-05-29
- Last updated: 2026-05-29

## Problem Statement

This backlog task was selected by `active-auto-loop` before a plan/handoff existed.
The task needs enough scoped context for an agent to decide whether it can be promoted
to `todo` or `ready` without rediscovering the queue entry.

## Current Behavior

- Queue status: `backlog`
- Owner role: `Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer`
- Queue title: Query rewrite and decomposition experiment

## Desired Behavior

Convert this draft into a concrete, execution-ready plan. Do not run implementation
work from this stub alone.

## Constraints

- Preserve `real100_v2` as the only current private eval surface unless explicitly changed.
- Do not expose raw private data, exact private filenames, raw questions, answers, doc IDs, or chunk IDs.
- Keep scope to one task concern.

## Task Breakdown

1. Read the queue entry and any linked reports or plans.
2. Fill in the concrete problem, affected files, validation commands, and reviewer focus.
3. Run the minimum safe preflight or explain why it cannot be run.
4. Update the Session Handoff below with real evidence.
5. Promote the task to `todo` or `ready` only after `handoff-check` passes.

## Acceptance Criteria

- [ ] This plan states the smallest executable scope.
- [ ] The Session Handoff has real validation evidence, not placeholder text.
- [ ] `handoff-check` passes before the task is selected for execution.

## Validation Strategy

```bash
python3 scripts/agent_loop.py handoff-check --task T-2026-0034
git diff --check
```

## Reviewer Notes

Attack scope drift first. This file was generated as backlog hydration, not as
evidence that the task is ready.

## Session Handoff - 2026-05-29 KST

- Role: Planner
- Lifecycle stage: backlog-prep
- Branch / worktree: [redacted-local-path]
- Task: T-2026-0034
- Current status: draft plan generated from backlog; not execution-ready.
- Files touched: docs/plans/T-2026-0034-query-rewrite-and-decomposition-experiment.md
- Commands run: not run
- Results: not run
- Validation evidence: not run
- Blockers: plan is a generated skeleton and still needs real task-specific evidence.
- Open risks: scope, validation commands, and reviewer focus may be incomplete.
- Next action: fill this plan with task-specific evidence and then promote the queue status to todo/ready.
- Next safe command: python3 scripts/agent_loop.py handoff-check --task T-2026-0034
- Reviewer focus: reject execution if this generated handoff still contains placeholder validation evidence.
