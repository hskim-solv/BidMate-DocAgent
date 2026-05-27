# Plan: T-2026-0020 PR corpus workset planning

- Status: review
- Owner role: Maintainer -> CI Reviewer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0020`
- Related issue: #1551

## Problem

`next-from-prs` sounded like it selected one open PR to continue. That is the
wrong operating model for the agent loop. Open PRs should be read as a corpus:
draft state, CI state, review state, merge blockers, stale signals, and claim
evidence together should produce the next task list.

The downstream commands also need to preserve that corpus-level decision.
`batch-plan` should group task briefs into worksets and lanes, and
`role-dispatch` should produce role-specific prompt inputs from that workset
plan. The root session should keep integration, validation, and ship gates.

## Desired Behavior

- `next-from-prs` treats open PRs as evidence, not as a PR selection list.
- Generated tasks are operational worksets such as blocked PR triage, ready PR
  ship lane, stale draft cleanup, private delta evidence, or draft workset
  continuation.
- Each task brief records `Source PRs`, `Workset`, `Lane`, `Role Hints`, and
  `Completion Proof`.
- `batch-plan` writes JSON with `workset_id`, `lane`, `source_prs`,
  `role_hints`, and `completion_proof`.
- `role-dispatch --batch` turns those worksets into Planner, Implementer,
  Reviewer, CI Reviewer, Benchmark Auditor, Privacy Auditor, and Deep Reviewer
  prompt source.
- `continue-loop` advances `pr-scan -> next-from-prs -> batch-plan ->
  role-dispatch -> draft/apply queue-plan -> loop-state` locally.

## Non-Goals

- Do not push, create/merge/close PRs, close issues, delete branches, force-push,
  run private real-eval, or approve benchmark/performance claims.
- Do not change retrieval, ingestion, eval scoring, answer contracts, or runtime
  behavior.
- Do not expose private raw values or PR body/title text as required evidence.

## Affected Interfaces

- `python3 scripts/agent_loop.py next-from-prs`
- `python3 scripts/agent_loop.py batch-plan`
- `python3 scripts/agent_loop.py role-dispatch --batch`
- `python3 scripts/agent_loop.py continue-loop`
- `scripts/ai_next_actions.py` generated Markdown, HTML, and task briefs
- `reports/agent_loop/batch_plan.json` local schema
- `tasks/queue.md` and `docs/plans/` operating docs

## Implementation Steps

1. Replace per-PR task generation with PR corpus signal classification.
2. Emit workset task briefs with source PR lists and completion proof.
3. Parse the new brief fields in `agent_loop.py`.
4. Extend `batch-plan` Markdown and JSON with workset metadata.
5. Wire `role-dispatch` to batch/workset inputs.
6. Add `continue-loop` to run the local planning chain and apply queue/plan
   only after internal agent-gate checks.
7. Update docs and persistent queue state.
8. Add focused tests for corpus planning, workset JSON, role dispatch, and
   local continuation.

## Validation Strategy

```bash
python3 -m py_compile scripts/ai_next_actions.py scripts/agent_loop.py
python3 -m pytest tests/test_ai_next_actions.py tests/test_agent_loop.py -q
python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-codex-workflow.md docs/operations/ai-engineering-operating-system.md tasks/queue.md docs/plans/T-2026-0020-pr-corpus-workset-planning.md
python3 scripts/agent_loop.py continue-loop --pr-json reports/agent_loop/pr_state.json --no-apply-queue-plan
git diff --check
make check-branch
```

## Acceptance Criteria

- Multiple PRs produce task/workset briefs from the corpus rather than a single
  PR selection.
- Blocked, ready, stale draft, private-delta, and draft continuation lanes can
  be represented with `Source PRs`.
- `batch-plan` separates serial, parallel-safe, review-only, and agent-gated
  lanes while preserving workset metadata.
- `role-dispatch` can render workset inputs from `batch_plan.json`.
- `continue-loop` creates local reports, drafts/apply queue-plan, and writes
  loop state without remote mutation.

## Rollback

Revert the `scripts/ai_next_actions.py`, `scripts/agent_loop.py`, tests, docs,
and queue/plan changes from this task. Generated `reports/agent_loop/*`
artifacts are gitignored and do not need rollback.

## Reviewer Focus

- Confirm `next-from-prs` no longer selects a single PR.
- Confirm task briefs do not leak private raw values or require raw PR text.
- Confirm `continue-loop` does not perform remote mutation.
- Confirm batch/workset lanes preserve serial dependencies and gate-sensitive
  surfaces.
- Confirm no benchmark, product quality, or private real-eval claim is implied.
