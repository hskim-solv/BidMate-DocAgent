# Plan Documents

Plan documents make larger AI-assisted work resumable across context
compaction, session handoffs, and reviewer changes. A good plan is not a design
essay; it is the smallest durable execution record that lets the next session
continue without rediscovering the same repo context.

Use [`TEMPLATE.md`](./TEMPLATE.md) for new plans. Use [`EXAMPLE.md`](./EXAMPLE.md)
as a realistic reference.

## When a Plan Is Required

Create a plan document before implementation when a task has any of these
properties:

- Multi-day, multi-session, or likely to survive context compaction.
- Changes more than one file or is expected to exceed roughly 50 LOC.
- Touches load-bearing paths, repo governance, eval/benchmark surfaces, public
  claims, or cross-agent workflow.
- Changes behavior and validation cannot be captured by one focused test or one
  obvious command.
- Requires sequencing across planner, implementer, evaluator, and reviewer
  roles.
- Needs rollback instructions because a bad change could invalidate metrics,
  break a contract, or confuse future agents.

## When a Plan Can Be Skipped

Skip the plan document when the task is small and locally obvious:

- Typo fixes, link fixes, or formatting-only changes.
- A single-line or single-file change with a direct validation command.
- A small documentation clarification that does not create or change policy.
- Mechanical updates where the PR description can fully capture context,
  validation, and rollback.

If the task starts small but reveals policy, eval, architecture, or handoff
risk, stop and create a plan before expanding the scope.

## How Plans Relate to Tasks and ADRs

- `tasks/queue.md` is the compact cross-session task index.
- `docs/plans/<task-id>-<slug>.md` is the execution record for large work.
- [`docs/adr/`](../adr/README.md) is the canonical home for durable decisions.
  Do not create a parallel root `adr/` tree in this repository.

Plans answer "how will we execute and verify this work?" ADRs answer "which
decision are future changes expected to respect?"

## Required Plan Content

Every plan must include:

- Title, owner role, status, and links to related task/issue/PR/ADR.
- Problem statement, current behavior, and desired behavior.
- Constraints, architecture impact, affected interfaces, and data/eval impact.
- Task breakdown, acceptance criteria, validation strategy, and rollback
  strategy.
- Failure modes, observability, reviewer notes, and handoff notes.

Each field must affect execution, review, or maintenance. If a field is not
applicable, write `N/A` plus the reason instead of leaving it blank.

## Handoff Discipline

Append a handoff note whenever a session pauses, context compacts, or ownership
changes. The next session should learn:

- What changed.
- What was validated.
- Which command is safe to run next.
- Which risks or open questions remain.

Do not use handoff notes as a diary. Keep them operational.
