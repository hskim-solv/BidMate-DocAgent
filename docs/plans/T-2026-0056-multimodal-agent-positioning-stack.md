# Plan: T-2026-0057+ Multimodal Agent positioning stack

- Status: proposed
- Owner role: Planner -> Reviewer
- Related task: `tasks/queue.md::T-2026-0057` through `T-2026-0070`
- Related issue / PR: [#1651](https://github.com/hskim-solv/BidMate-DocAgent/issues/1651) / N/A
- Related ADR: N/A - no decision-level runtime change
- Created: 2026-05-28
- Last updated: 2026-05-28

## Problem Statement

BidMate-DocAgent already demonstrates RFP-specific Agentic RAG, evaluation
rigor, citation grounding, and CI/provenance gates. The portfolio framing is
still too narrow if it reads as "RAG engineer only", and stale legacy private
eval wording can conflict with the current `real100_v2`-only evidence policy.

The next stack should reposition the repo as evidence for a Multimodal Agentic
AI Product Engineer profile while keeping every new capability opt-in and
evidence-gated.

## Current Behavior

- Runtime defaults remain extractive, citation-grounded RAG.
- `real100_v2` is the current private eval evidence lane for new work.
- Earlier-generation private-eval artifacts and wording are archive-only and
  must not back new claims.
- `T-2026-0056` already exists on `origin/main` as the Ollama local
  OpenAI-compatible provider spike, so this stack starts at `T-2026-0057`.

## Desired Behavior

- README and portfolio pitch describe the repo as an Agentic RAG foundation that
  can expand toward multimodal, agent, product, and self-hosted serving work.
- `tasks/queue.md` contains executable follow-up tasks for the full positioning
  stack without changing runtime behavior.
- Any future VLM, agent, product API, graph, or vLLM-style work has an explicit
  evidence boundary, privacy boundary, and validation route before it starts.

## Constraints

- Scope constraints: docs/task queue only for the first PR.
- Architecture constraints: no runtime, API, schema, eval scoring, or default
  pipeline changes in this task.
- Compatibility constraints: preserve ADR 0001 `naive_baseline`, ADR 0003
  answer dict contract, and existing FastAPI/demo behavior.
- Eval/privacy constraints: use `real100_v2` aggregate-only for new private
  evidence; commit no raw private text, page images, filenames, local paths,
  `doc_id`, or `chunk_id`.
- Tooling/CI constraints: keep follow-up implementation tasks issue-linked and
  one concern per PR.
- Non-goals: do not implement VLM captioning, new Agent tools, Graph RAG, or
  self-hosted serving in this planning PR.

## Architecture Impact

- Affected modules or docs: `README.md`, `docs/portfolio-pitch.md`,
  `tasks/queue.md`, this plan.
- Affected contracts or invariants: documentation and task queue only.
- Load-bearing paths: none changed.
- ADR required: no, because this is planning/wording only.
- Backward compatibility expectation: no behavior change.

## Affected Interfaces

- CLI/API/config: unchanged.
- Input data: unchanged.
- Output artifacts: no new generated artifacts.
- Docs/review surfaces: README, portfolio pitch, task queue, plan.
- Tests/eval entrypoints: doc link check, `real100_v2` guard, claim audit.

## Data / Eval Impact

- Surface: none for runtime; private eval policy wording only.
- Data boundary: no data touched.
- Allowed claim: the repo is planning an opt-in Multimodal Agent/Product
  positioning track.
- Disallowed claim: VLM, Agent, Graph RAG, vLLM, or product quality has already
  improved because of this PR.
- Baseline or control affected: no.
- Benchmark/eval auditor required: privacy/evidence wording review only.

## Task Breakdown

1. Update README and portfolio pitch to remove stale legacy private eval wording
   from current claims and state the `real100_v2` boundary.
2. Add `T-2026-0057` through `T-2026-0070` to `tasks/queue.md`.
3. Record that `T-2026-0056` is already occupied by the Ollama provider spike,
   so the requested stack is shifted by one ID without changing intent.
4. Validate doc links, `real100_v2` guard, claim audit, whitespace, and branch
   convention.

## Acceptance Criteria

- [ ] README and portfolio pitch no longer use earlier-generation private-eval
  wording as current claim evidence.
- [ ] Queue tasks cover positioning, external source audit, visual evidence,
  VLM, agent state/security, multimodal vertical slice, trajectory eval,
  product API, self-hosted serving, graph feasibility, interview pack, and
  review board refresh.
- [ ] Follow-up task boundaries make runtime changes opt-in and issue-linked.

## Validation Strategy

Commands that must be run:

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md docs/portfolio-pitch.md README.md
make real-eval-v2-guard
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: doc links, `real100_v2` guard, claim audit, branch check.
- Generated or updated artifact: none.
- Reviewer checklist or manual inspection: stale private eval wording and
  over-claim risk.
- Explicitly not validated, with reason: no VLM/Agent/Product runtime behavior
  is implemented in this PR.

## Rollback Strategy

Revert the docs/task-only commit. Do not delete existing `real100_v2` aggregate
artifacts or the pre-existing `T-2026-0056` Ollama task.

## Failure Modes

- Failure mode: duplicate task ID with existing `T-2026-0056`.
- Detection signal: `rg "T-2026-0056" tasks/queue.md`.
- Stop condition or fallback: keep existing task and shift this stack to
  `T-2026-0057` through `T-2026-0070`.

- Failure mode: new wording implies implemented multimodal capability.
- Detection signal: claim audit or reviewer inspection.
- Stop condition or fallback: rewrite as task stack / planned opt-in work.

- Failure mode: external framework claims become uncited trend-chasing.
- Detection signal: `T-2026-0059` cannot verify source docs or repo grounding.
- Stop condition or fallback: keep only internal ADR/repo evidence.

## Observability

- `tasks/queue.md` ready-order rows and task detail sections.
- README and portfolio pitch wording.
- `real100_v2` guard output.
- Claim audit output.

## Reviewer Notes

Attack over-claiming first: this PR should change positioning and task planning
only. It must not claim VLM, Agent, product, Graph RAG, or self-hosted serving
capability beyond existing repo evidence.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 KST

- Role: Planner
- Branch / worktree: docs/issue-1651-multimodal-agent-positioning-stack / /Users/hskim/.codex/worktrees/a7c0/BidMate-DocAgent
- Issue / PR: #1651 / N/A
- Task: T-2026-0057 through T-2026-0070
- Current status: docs/task-only stack implemented and locally validated.
- Files touched: README.md, docs/portfolio-pitch.md, docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md, tasks/queue.md
- Decisions made: preserve existing T-2026-0056 Ollama task and shift the new stack to T-2026-0057..0070.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md docs/portfolio-pitch.md README.md; make real-eval-v2-guard; python3 scripts/agent_loop.py claim-audit --from-git; git diff --check; make check-branch
- Results: all passed.
- Next safe command: git diff --stat
- Open questions: none.
- Risks: wording over-claims planned multimodal/agent/product work.
```
