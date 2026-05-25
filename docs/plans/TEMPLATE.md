# Plan: <task-id> <title>

- Status: proposed | running | blocked | review | done
- Owner role: <Planner | Implementer | Evaluator | Reviewer | other role>
- Related task: `tasks/queue.md::<task-id>` | N/A
- Related issue / PR: <links or N/A>
- Related ADR: <links or "N/A - no decision-level change">
- Created: YYYY-MM-DD
- Last updated: YYYY-MM-DD

## Problem Statement

State the concrete failure, bottleneck, missing capability, or coordination risk.
Name the user-visible or reviewer-visible consequence if this plan is not done.

## Current Behavior

Describe the current workflow or implementation enough for a new session to
resume without rediscovery. Include relevant files, commands, docs, ADRs,
observed outputs, and known failure modes.

## Desired Behavior

Describe the smallest useful end state. This must be observable through a
command, artifact, review checklist, or explicit non-change claim.

## Constraints

- Scope constraints:
- Architecture constraints:
- Compatibility constraints:
- Eval/privacy constraints:
- Tooling/CI constraints:
- Non-goals:

## Architecture Impact

- Affected modules or docs:
- Affected contracts or invariants:
- Load-bearing paths:
- ADR required: yes/no, with reason:
- Backward compatibility expectation:

## Affected Interfaces

- CLI/API/config:
- Input data:
- Output artifacts:
- Docs/review surfaces:
- Tests/eval entrypoints:

## Data / Eval Impact

- Surface: public fixture smoke | public synthetic benchmark | private real-eval | none
- Data boundary: public fixture | aggregate-only private output | no data touched | other:
- Allowed claim:
- Disallowed claim:
- Baseline or control affected: yes/no, with reason:
- Benchmark/eval auditor required: yes/no:

## Task Breakdown

1. <Actionable step and target file/surface>
2. <Actionable step and target file/surface>
3. <Actionable step and target file/surface>

## Acceptance Criteria

- [ ] <Observable criterion tied to desired behavior>
- [ ] <Contract or documentation criterion>
- [ ] <Validation evidence criterion>

## Validation Strategy

Commands that must be run:

```bash
# command
```

Expected evidence:

- Test/eval output:
- Generated or updated artifact:
- Reviewer checklist or manual inspection:
- Explicitly not validated, with reason:

## Rollback Strategy

Explain how to revert safely if the change regresses behavior, invalidates an
eval claim, or creates operational risk. Name any data/artifacts that must not
be deleted during rollback.

## Failure Modes

- Failure mode:
- Detection signal:
- Stop condition or fallback:

## Observability

List the logs, reports, metrics, traces, CI checks, or review artifacts that
show whether the work is succeeding or failing. Prefer stable paths and command
outputs over narrative promises.

## Reviewer Notes

Tell the reviewer what to attack first: claim wording, contract drift,
baseline preservation, data boundary, rollback path, missing tests, or another
specific risk.

## Handoff Notes

Update this section at every session boundary or context compaction.

```markdown
## Session Handoff - YYYY-MM-DD HH:MM TZ

- Role:
- Branch / worktree:
- Issue / PR:
- Task:
- Current status:
- Files touched:
- Decisions made:
- Commands run:
- Results:
- Next safe command:
- Open questions:
- Risks:
```
