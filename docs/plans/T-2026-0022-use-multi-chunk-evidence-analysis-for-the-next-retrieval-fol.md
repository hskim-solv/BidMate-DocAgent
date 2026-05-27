# Plan: T-2026-0022 Use multi-chunk evidence analysis for the next retrieval follow-up

- Status: draft
- Owner role: Planner -> Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0022`
- Related issue / PR: [#1563](https://github.com/hskim-solv/BidMate-DocAgent/issues/1563) / PR TBD
- Source brief: `reports/agent_loop/codex_tasks/001-multi-chunk-follow-up.md`
- Suggested final path: `docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`

## Problem

multi-chunk aggregate is available: 97/99 top-10 failures; 97 limited-depth cases

## Desired Outcome

Turn the aggregate multi-chunk evidence split into one scoped measurement follow-up.

## Scope

- Convert the planner brief into one narrow, reviewable Codex task.
- Reuse existing BidMate operating docs, queue, plans, validation commands, and reviewer prompts.
- Keep generated artifacts local unless a human promotes a redacted artifact.

## Out of Scope

- Auto-merge, auto-push, PR creation/close/merge, branch deletion, or force-push.
- Benchmark, performance, private real-eval, or architecture tradeoff decisions without ADR 0079 agent-gate evidence.
- Raw private question, answer, evidence, doc_id, chunk_id, filenames, or exact local paths.

## Surface / Claim Boundary

- Initial classification: `next_experiment_candidate`
- Workset: `general`
- Source PRs: `PR corpus`
- Lane: `parallel-safe`
- Eval surface: classify again after implementation if changed files touch eval, benchmark, metrics, reports, configs, or claims.
- Disallowed claim: do not claim product quality, benchmark lift, or private real-eval success from this draft alone.

## Implementation Steps

1. Read the required operating docs and this plan.
2. Inspect the cited workflow surface and existing tests.
3. Make the smallest scoped change.
4. Add or update focused tests.
5. Run focused validation and `git diff --check`.
6. Leave a handoff with required fields and reviewer focus.

## Validation

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py
git diff --check
```

## Reviewer Focus

- Scope control against the source brief.
- Completion proof: Focused validation passes and the follow-up evidence is recorded.
- Privacy boundary and claim wording.
- Conservative eval surface classification.
- Validation evidence matches commands actually run.

## Session Handoff

- Role:
- Lifecycle stage:
- Branch / worktree:
- Task: T-2026-0022
- Current status:
- Files touched:
- Commands run:
- Results:
- Validation evidence: [redacted-private-value]
- Open risks:
- Next action:
- Next safe command:
- Reviewer focus:
- Eval surface:
