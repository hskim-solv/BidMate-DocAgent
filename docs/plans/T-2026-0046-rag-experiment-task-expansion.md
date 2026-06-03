# Plan: T-2026-0046 RAG experiment task expansion

- Status: review
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0046`
- Related issue / PR: [#1627](https://github.com/hskim-solv/BidMate-DocAgent/issues/1627) / PR TBD
- Related ADR: N/A - no runtime or eval contract change
- Created: 2026-05-28
- Last updated: 2026-06-03

## Problem Statement

The current RAG performance stack has implementation-oriented backlog items,
but it does not yet give future sessions enough experiment tasks to reach a
final optimization decision. It also lacks explicit replanning checkpoints, so a
session could keep executing stale hypotheses after early measurements already
show a better direction.

## Current Behavior

Current main has:

- `T-2026-0028`: `real100_v2` aggregate baseline and stale-evidence guard.
- `T-2026-0029`: retrieval diagnostics showing dominant
  `not_observable_limited_depth`, page metadata coverage `0.0`, and
  `T-2026-0032` as the next candidate while `T-2026-0031` remains blocked.
- `T-2026-0030`: ready latency/cost envelope task.
- `T-2026-0031` through `T-2026-0039`: broad experiment and feasibility
  backlog, but without experiment-round synthesis gates or final decision
  packet tasks.

## Desired Behavior

The queue should guide performance work through measured rounds:

1. Complete latency/cost and early retrieval measurements.
2. Replan from evidence.
3. Run the most relevant P1 experiments.
4. Replan again.
5. Run an end-to-end bakeoff.
6. Produce a final default-change, further-experiment, or no-go decision.

## Constraints

- Scope constraints: docs, task queue, and evaluation note only.
- Architecture constraints: no retrieval, reranking, parser, prompt, eval
  runtime, or index behavior changes.
- Compatibility constraints: preserve existing task IDs and existing experiment
  scopes.
- Eval/privacy constraints: no current `real100_v2` private-eval run; no raw
  private content, filenames, local paths, `doc_id`, or `chunk_id`.
- Tooling/CI constraints: doc-link check, whitespace check, and branch/issue
  check only.
- Non-goals: do not create implementation issues for every future task now.

## Architecture Impact

- Affected modules or docs: `tasks/queue.md`,
  `docs/evaluation/rag-performance-experiment-stack.md`, and this plan doc.
- Affected contracts or invariants: planning workflow only.
- Load-bearing paths: none.
- ADR required: no, because this is docs/planning only.
- Backward compatibility expectation: all existing runtime and eval commands
  remain unchanged.

## Affected Interfaces

- CLI/API/config: none.
- Input data: none.
- Output artifacts: planning docs only.
- Docs/review surfaces: task queue and experiment stack.
- Tests/eval entrypoints: doc-link validation only.

## Data / Eval Impact

- Surface: none.
- Data boundary: no data touched.
- Allowed claim: the experiment queue now has explicit measurement and
  replanning gates.
- Disallowed claim: retrieval quality, answer quality, latency, citation,
  security, or production performance improved.
- Baseline or control affected: no.
- Benchmark/eval auditor required: yes, to review whether experiment order and
  claim boundaries are coherent.

## Task Breakdown

1. Add `T-2026-0046` through `T-2026-0055` queue entries for experiment
   expansion, page metadata unblock, retrieval depth/fusion, two replanning
   gates, parser/layout, embedding, generator grounding, bakeoff, and final
   decision.
2. Update `docs/evaluation/rag-performance-experiment-stack.md` with cadence,
   replanning gates, metrics, and execution rules.
3. Add this plan document and validate links.

## Acceptance Criteria

- [x] The queue contains experiment tasks that cover data/parser, retrieval,
  reranking, context, query, metadata, embedding, generator, advanced
  architecture, and end-to-end bakeoff surfaces.
- [x] The queue includes replanning tasks after early retrieval evidence and
  after the full P1 experiment round.
- [x] The final optimization decision is separated from the implementation of a
  default behavior change.

## Validation Strategy

Commands that must be run:

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: N/A - no runtime or eval behavior changed.
- Generated or updated artifact: docs and queue entries only.
- Reviewer checklist or manual inspection: task ordering, replanning gates,
  private boundary, and no-claim wording.
- Explicitly not validated, with reason: no current `real100_v2` private eval
  because this PR only creates task structure.

## Rollback Strategy

Revert this docs/planning PR if the expanded stack makes execution order less
clear or creates overlapping task scopes. Do not delete existing experiment
reports, private local runs, or prior plan docs.

## Failure Modes

- Failure mode: future agents treat isolated experiment winners as default-ready.
- Detection signal: a PR flips runtime defaults without `T-2026-0054` bakeoff
  and `T-2026-0055` decision evidence.
- Stop condition or fallback: block the default-change PR and route it through
  bakeoff and decision packet tasks.

- Failure mode: future sessions execute stale backlog order after measurements
  identify a different bottleneck.
- Detection signal: `T-2026-0049` or `T-2026-0053` is skipped while later
  experiment tasks proceed.
- Stop condition or fallback: pause implementation and run the relevant
  replanning gate.

## Observability

- `tasks/queue.md` ready/backlog/blocked statuses.
- `docs/evaluation/rag-performance-experiment-stack.md` cadence and gates.
- Future current `real100_v2` aggregate-only synthesis reports from
  `T-2026-0049`, `T-2026-0053`, and `T-2026-0055`.

## Reviewer Notes

Attack overlap and claim boundaries first. The new tasks should make the path
to final optimization more rigorous, but they must not imply any current RAG
performance improvement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 KST

- Role: Planner
- Branch / worktree: docs/issue-1627-rag-experiment-task-stack / /Users/hskim/.codex/worktrees/de70/BidMate-DocAgent
- Issue / PR: issue #1627 / PR TBD
- Task: T-2026-0046
- Current status: queue, experiment stack, and plan doc drafted.
- Files touched: tasks/queue.md, docs/evaluation/rag-performance-experiment-stack.md, docs/plans/T-2026-0046-rag-experiment-task-expansion.md
- Decisions made: add experiment execution tasks plus replanning gates; keep final default-change decision as its own task.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md; git diff --check; make check-branch.
- Results: passed.
- Next safe command: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md
- Open questions: none.
- Risks: future agents may over-combine variants before the bakeoff task.
```
