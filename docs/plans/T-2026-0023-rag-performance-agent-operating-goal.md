# Plan: T-2026-0023 RAG performance agent operating goal

- Status: review
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0023`
- Related issue / PR: [#1569](https://github.com/hskim-solv/BidMate-DocAgent/issues/1569) / [#1570](https://github.com/hskim-solv/BidMate-DocAgent/pull/1570)
- Related ADR: N/A - no decision-level runtime or eval contract change
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

The agent loop can make progress by fixing small orchestration bugs, but the
longer goal is to improve RAG system performance. Without a tracked operating
goal, future sessions can over-optimize for tiny local fixes, skip role
separation, or forget to invest in process improvements that make larger RAG
work reliable.

## Current Behavior

The repository already has the core operating surfaces:

- `tasks/queue.md` stores persistent task state.
- `docs/plans/TEMPLATE.md` defines plan docs for non-trivial work.
- `docs/operations/ai-engineering-operating-system.md` defines role and review
  escalation.
- `docs/operations/long-session-workflow.md` preserves handoff state.
- `docs/agent-utilization.md` maps rules, skills, subagents, and commands.
- `scripts/agent_loop.py continue-loop` generates queue/plan/role-dispatch
  artifacts.

The missing part is an explicit long-running RAG performance goal that binds
these surfaces to the 8 operating principles.

## Desired Behavior

New sessions should treat RAG performance improvement as a broad, multi-session
program while still shipping one concern per PR. The first screen for future
agents should make the expected operating shape clear: queue-backed work,
plan-backed scope, role-separated sessions, adversarial review, conservative
human gates, and periodic process improvement.

## Constraints

- Scope constraints: docs/governance only for this PR.
- Architecture constraints: do not change retrieval, reranking, answer,
  ingestion, API, or eval runtime behavior.
- Compatibility constraints: preserve existing task queue and plan doc formats.
- Eval/privacy constraints: no private real-eval run, no raw private artifact
  content, and no exact local private path in tracked docs.
- Tooling/CI constraints: use targeted doc-link checks plus branch/issue checks.
- Non-goals: do not add code automation, CI gates, metrics, or benchmark
  outputs in this PR.

## Architecture Impact

- Affected modules or docs: `tasks/queue.md`,
  `docs/operations/ai-engineering-operating-system.md`,
  `docs/operations/long-session-workflow.md`,
  `docs/operations/ai-codex-workflow.md`, `docs/agent-utilization.md`.
- Affected contracts or invariants: operating workflow only.
- Load-bearing paths: none.
- ADR required: no, this does not change a load-bearing runtime or eval
  contract.
- Backward compatibility expectation: existing queue, plan, review, and
  continue-loop workflows remain valid.

## Affected Interfaces

- CLI/API/config: none.
- Input data: none.
- Output artifacts: docs and task queue only.
- Docs/review surfaces: agent-loop operating docs and handoff checklist.
- Tests/eval entrypoints: doc-link validation only.

## Data / Eval Impact

- Surface: none.
- Data boundary: no data touched.
- Allowed claim: operating-goal alignment for future RAG performance work.
- Disallowed claim: RAG quality, retrieval quality, answer quality, latency,
  recall, nDCG, or production performance improved.
- Baseline or control affected: no.
- Benchmark/eval auditor required: yes for future performance claims; this PR
  only records that requirement.

## Task Breakdown

1. Add a ready queue entry for the long-running RAG performance operating goal.
2. Add this plan doc with the 8 operating principles as acceptance criteria.
3. Update operating docs so future sessions know how to apply the principles.
4. Validate links, branch/issue convention, and claim wording.

## Operating Principles

1. Broad outcome scope: set RAG performance improvement as the program-level
   goal, then split implementation into one concern per PR.
2. Long sessions: keep work alive through queue, plan, handoff, and follow-up
   tasks instead of transcript memory.
3. Todo/file queue: put next actions, blockers, and completion proof in tracked
   docs.
4. Plan docs: use plan docs before broad, multi-file, eval, or load-bearing work.
5. Adversarial review: attach Reviewer, Deep Reviewer, Benchmark Auditor, and
   Privacy Auditor when the surface requires them.
6. Role-separated sessions: split Planner, Implementer, Tester/CI Reviewer,
   Issue Triage, Deep Reviewer, Benchmark Auditor, and Privacy Auditor when
   work can proceed independently.
7. Human outside the loop: automation should execute and produce evidence;
   humans double-check evidence and approve conservative gates only.
8. Process improvement: when repeated misses appear, spend at least 20% of loop
   time improving instructions, harnesses, queue quality, or review prompts.

## Acceptance Criteria

- [ ] `tasks/queue.md` contains a ready task for the long-running RAG performance
  goal.
- [ ] The 8 principles are reflected in operating docs, not only in this plan.
- [ ] Role separation explicitly includes Planner, Implementer, Tester/CI
  Reviewer, Issue Triage, Deep Reviewer, Benchmark Auditor, Privacy Auditor,
  and Reviewer.
- [ ] Claim wording says this PR is docs/governance only and makes no RAG
  performance claim.
- [ ] Validation evidence is recorded without private raw data.

## Validation Strategy

Commands that must be run:

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md docs/operations/ai-engineering-operating-system.md docs/operations/long-session-workflow.md docs/operations/ai-codex-workflow.md docs/agent-utilization.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: N/A - no runtime or eval behavior changed.
- Generated or updated artifact: docs and queue entries only.
- Reviewer checklist or manual inspection: claim boundary and role separation.
- Explicitly not validated, with reason: no private real-eval because this PR
  does not change RAG runtime behavior or make a performance claim.

## Rollback Strategy

Revert this docs/governance PR if the operating wording causes workflow
confusion. Do not delete any unrelated task queue entries or plan docs during
rollback.

## Failure Modes

- Failure mode: future agents treat broad scope as permission to mix concerns in
  one PR.
- Detection signal: PR contains unrelated runtime, eval, ADR, and docs changes.
- Stop condition or fallback: split work into issue-linked PRs and keep only one
  concern per branch.

- Failure mode: governance wording is mistaken for a performance claim.
- Detection signal: PR body or docs imply RAG quality improved.
- Stop condition or fallback: remove the claim and require private real-eval
  aggregate paired delta before performance wording.

## Observability

- `tasks/queue.md` Ready Order shows the long-running operating goal.
- Future task entries link back to this plan when they are part of the RAG
  performance program.
- PR bodies include whether the change is docs/governance only or includes a
  validated performance claim.

## Reviewer Notes

Attack claim wording first. This PR should make future RAG performance work more
operable, but it must not claim any current RAG performance improvement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 15:16 KST

- Role: Planner / Implementer
- Branch / worktree: docs/issue-1569-rag-performance-agent-goal / /Users/hskim/.codex/worktrees/3165/BidMate-DocAgent
- Issue / PR: #1569 / PR #1570
- Task: T-2026-0023
- Current status: docs/governance implementation opened as PR #1570.
- Files touched: tasks/queue.md, docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md, docs/operations/ai-engineering-operating-system.md, docs/operations/long-session-workflow.md, docs/operations/ai-codex-workflow.md, docs/agent-utilization.md
- Decisions made: keep this as docs/governance only; no runtime or eval changes.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md docs/operations/ai-engineering-operating-system.md docs/operations/long-session-workflow.md docs/operations/ai-codex-workflow.md docs/agent-utilization.md; git diff --check; make check-branch
- Results: passed.
- Next safe command: make ship-review-gate PR=1570
- Open questions: none.
- Risks: claim wording could be overread as a performance result.
```
