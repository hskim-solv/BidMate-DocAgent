# Plan: T-2026-0019 Agent loop continuation repair

- Status: review
- Owner role: Maintainer -> CI Reviewer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0019`
- Issue: #1549

## Problem

`loop-state` records the current gate, surface, manifest freshness, and task
state, but it does not provide a single machine-readable continuation plan when
the loop is interrupted by detached HEAD, missing task linkage, or a stale
manifest. The result is a safe stop, but not an obvious next automated recovery
step.

## Desired Outcome

`loop-state` should expose a `continuation` block that names blockers, warnings,
whether automation can continue, and the next safe command sequence. The
dashboard should render the same status for human review.

## Scope

- Add continuation metadata to `scripts/agent_loop.py` loop-state output.
- Render continuation status in the dashboard.
- Add focused regression coverage for detached HEAD repair and ready issue
  branch continuation.
- Document the continuation block in the operating-system doc.

## Non-Goals

- Do not execute push, PR creation, merge, branch deletion, force-push, or
  private real-eval from `loop-state`.
- Do not remove `make ship-arm` single-shot behavior.
- Do not hide task/plan linkage gaps.

## Validation Strategy

```bash
python3 -m py_compile scripts/agent_loop.py
python3 -m pytest tests/test_agent_loop.py -q
python3 -m pytest tests/test_agent_loop_claude_integration.py -q
python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-engineering-operating-system.md tasks/queue.md docs/plans/T-2026-0019-agent-loop-continuation-repair.md
git diff --check
make check-branch
```

## Rollback Strategy

Revert the `continuation` helper, dashboard section, tests, and documentation.
Existing gate-status, manifest, and auto-ship commands remain independent.

## Failure Modes

- Recovery command could imply bypassing conservative gates.
- Detached HEAD repair could create an issue-linked branch but still lack a task
  id.
- A stale manifest could make automation believe the current diff is older than
  it is.

## Reviewer Notes

This is tooling/governance only. It does not change retrieval, answer behavior,
eval scoring, private data handling, or shipping mutation behavior.
