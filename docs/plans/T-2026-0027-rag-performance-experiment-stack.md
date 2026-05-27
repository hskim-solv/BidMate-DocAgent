# Plan: T-2026-0027 RAG performance experiment stack

- Status: review
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0027`
- Related issue / PR: [#1584](https://github.com/hskim-solv/BidMate-DocAgent/issues/1584) / [#1587](https://github.com/hskim-solv/BidMate-DocAgent/pull/1587)
- Related ADR: N/A - no runtime or eval contract change
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

The RAG performance goal is now explicit, but the next work is still too broad
to execute safely. A generic list of RAG techniques can push the project toward
expensive experiments before the private real-eval baseline, failure taxonomy,
latency envelope, and privacy boundaries are strong enough to support a real
performance claim.

Without a concrete stack, future sessions can mix data readiness, retrieval,
reranking, context packing, generator behavior, security, and advanced
architecture work in one PR. That would violate the one-concern rule and make
paired delta evidence hard to trust.

## Current Behavior

The current main branch already contains important prerequisites:

- `T-2026-0022` recorded the multi-chunk retrieval no-go until page-aware
  evidence can distinguish same-document and multi-document evidence splits.
- `T-2026-0023` set the long-running RAG performance operating goal.
- `T-2026-0024` recovered page metadata at index build time.
- `T-2026-0025` separated hashing, MiniLM, and BGE-M3 private real-eval
  surfaces.
- `T-2026-0026` split Chroma vector-store work into a backend-axis task rather
  than a quality-improvement experiment.
- `docs/evaluation/surface-map.md` already requires private real-eval aggregate
  paired deltas for real performance claims.
- `docs/evaluation/pre_improvement_readiness_checklist.md` already requires
  parse audit -> eval dataset audit -> validate-only -> baseline run -> failure
  taxonomy -> improvement hypothesis.

The missing piece is a repo-native task stack that converts the broad RAG
performance checklist into ordered, scoped, measurable tasks.

## Desired Behavior

Future sessions should start from a prioritized queue:

1. Build or refresh measurement evidence before changing behavior.
2. Run retrieval experiments only when the candidate pool and gold evidence
   diagnostics can explain the expected metric movement.
3. Add reranking, context packing, query rewriting, no-answer, conflict, and
   metadata changes behind opt-in experiment surfaces.
4. Treat GraphRAG, RAPTOR, LightRAG, Agentic RAG, late chunking, multi-vector
   retrieval, and long-context RAG as feasibility work until private aggregate
   evidence shows the simpler stack is exhausted.

The observable output is a queue-backed stack plus a durable evaluation note,
not a runtime quality change.

## Constraints

- Scope constraints: docs, task queue, and planning surfaces only.
- Architecture constraints: do not change retrieval, reranking, answer,
  ingestion, API, eval runtime, or index-building behavior in this PR.
- Compatibility constraints: preserve existing task and plan formats.
- Eval/privacy constraints: no private real-eval run, no raw private content,
  no exact local private path, no `doc_id` or `chunk_id` in committed docs.
- Tooling/CI constraints: validate doc links, whitespace, and branch/issue
  convention.
- Non-goals: do not create all future GitHub issues now; create issue-linked
  branches when each task starts.

## Architecture Impact

- Affected modules or docs: `tasks/queue.md`,
  `docs/evaluation/rag-performance-experiment-stack.md`,
  `docs/evaluation/surface-map.md`, and this plan doc.
- Affected contracts or invariants: planning and review workflow only.
- Load-bearing paths: none.
- ADR required: no, this does not introduce a new metric contract or runtime
  architecture decision.
- Backward compatibility expectation: existing eval, retrieval, and agent-loop
  commands remain unchanged.

## Affected Interfaces

- CLI/API/config: none.
- Input data: none.
- Output artifacts: planning docs only.
- Docs/review surfaces: task queue, evaluation surface map, experiment stack.
- Tests/eval entrypoints: doc-link validation only.

## Data / Eval Impact

- Surface: none.
- Data boundary: no data touched.
- Allowed claim: a prioritized experiment backlog was created.
- Disallowed claim: retrieval quality, answer quality, latency, citation,
  abstention, security, or production performance improved.
- Baseline or control affected: no.
- Benchmark/eval auditor required: yes, to review the selected experiment order
  and claim boundaries.

## Task Breakdown

1. Sync prerequisite queue entries whose merge state is already visible on
   current main.
2. Add a selected experiment stack document that maps broad RAG levers to
   concrete BidMate tasks and defers low-evidence techniques.
3. Add queue entries for P0/P1/P2/P3 tasks with dependencies, surfaces,
   validation commands, and evidence requirements.
4. Link the stack from the evaluation surface map.
5. Validate links and branch hygiene.

## Acceptance Criteria

- [x] `tasks/queue.md` contains a current planning task and a concrete
  prioritized follow-up stack.
- [x] Every follow-up task has a priority, dependency, scope, non-goal,
  acceptance criteria, validation command, and evidence boundary.
- [x] The stack explains why some advanced RAG techniques are deferred.
- [x] Wording clearly says this PR is docs/planning only and makes no RAG
  performance claim.
- [x] Validation evidence is recorded without private raw data.

## Validation Strategy

Commands that must be run:

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0027-rag-performance-experiment-stack.md docs/evaluation/rag-performance-experiment-stack.md docs/evaluation/surface-map.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: N/A - no runtime or eval behavior changed.
- Generated or updated artifact: docs and queue entries only.
- Reviewer checklist or manual inspection: priority order, dependency order,
  no-claim wording, and private boundary.
- Explicitly not validated, with reason: no private real-eval because this PR
  only creates the task stack.

## Rollback Strategy

Revert this docs/planning PR if the stack confuses execution order or pushes
too much work into one PR. Do not delete unrelated existing task entries or
plan docs during rollback.

## Failure Modes

- Failure mode: future agents treat the stack as permission to implement
  multiple experiment tasks in one branch.
- Detection signal: a PR changes retrieval, reranking, context packing, prompt,
  security, and eval metrics together.
- Stop condition or fallback: split the PR by task ID and keep only one concern
  per branch.

- Failure mode: a task claims performance from public fixture or synthetic
  output.
- Detection signal: PR body lacks private aggregate paired delta provenance.
- Stop condition or fallback: downgrade the claim to regression or measurement
  only.

- Failure mode: a task commits raw private identifiers.
- Detection signal: committed artifact includes raw question, answer, evidence,
  filename, exact local path, `doc_id`, or `chunk_id`.
- Stop condition or fallback: remove the artifact and replace it with
  aggregate-only evidence.

## Observability

- `tasks/queue.md` shows the next executable P0 task.
- `docs/evaluation/rag-performance-experiment-stack.md` explains why each task
  is selected or deferred.
- Future PR bodies can cite a task ID and state the allowed claim surface.

## Reviewer Notes

Attack priority order and claim boundaries first. This PR should make future
RAG performance work more executable, but it must not imply any current quality
or latency improvement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 20:00 KST

- Role: Planner
- Branch / worktree: docs/issue-1584-rag-performance-experiment-stack / Codex worktree
- Issue / PR: #1584 / #1587
- Task: T-2026-0027
- Current status: task stack docs implemented and validation passed.
- Files touched: tasks/queue.md, docs/plans/T-2026-0027-rag-performance-experiment-stack.md, docs/evaluation/rag-performance-experiment-stack.md, docs/evaluation/surface-map.md
- Decisions made: prioritize measurement readiness and retrieval diagnostics before advanced architectures; keep Chroma as a separate backend-axis task.
- Commands run: python3 scripts/agent_loop.py overlap-preflight --issue 1584 --branch docs/issue-1584-rag-performance-experiment-stack; python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0027-rag-performance-experiment-stack.md docs/evaluation/rag-performance-experiment-stack.md docs/evaluation/surface-map.md; git diff --check; make check-branch.
- Results: passed.
- Next safe command: git diff --stat
- Open questions: none.
- Risks: task stack may need issue split before implementation starts.
```
