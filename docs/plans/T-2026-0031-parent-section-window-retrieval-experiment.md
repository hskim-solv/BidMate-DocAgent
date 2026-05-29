# Plan: T-2026-0031 parent and section-window retrieval experiment

- Status: running
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0031`
- Related issue / PR: issue #1667 / PR TBD

## Purpose

Test whether small-to-big retrieval can improve same-document multi-chunk and
page/window evidence failures on the MiniLM page-aware `real100_v2` index.

## Current Scope

This branch is currently repairing the active loop and measurement prerequisites
needed before the retrieval experiment can run safely:

- `make 시작` must select a branch-aligned task, use the current changed-file
  surface, run bounded Codex review lanes, and stop after the configured task
  limit.
- The start alias must not execute ship by default.
- Local gate completion must require runner + conservative gate evidence, not a
  read-only report alone.
- `real100_v2` judge and rationality aggregate wiring must exist before answer
  generation claims are made.

## Experiment Work After Gate Repair

1. Preserve the ADR 0001 `naive_baseline` invariant.
2. Add an opt-in parent/section/page-window retrieval variant.
3. Deduplicate expanded context and cap latency/token growth.
4. Compare against the refreshed checkpoint MiniLM page-aware `real100_v2`
   baseline with paired aggregate delta.
5. Report same-document multi-chunk cases separately from multi-document cases.

## Eval Surface

- Surface: private real-eval / eval-harness.
- Current claim: automation and measurement surface wiring only.
- Disallowed claim: no parent/window retrieval quality improvement claim until
  paired `real100_v2` aggregate evidence exists.

## Validation Plan

```bash
python3 -m py_compile scripts/agent_loop.py scripts/llm_judge.py eval/judges/llm_judge.py
python3 -m pytest -q tests/test_agent_loop.py -k 'active_auto_loop or make_active_start or active_codex_runner'
python3 -m pytest -q tests/test_llm_judge.py -k 'CLI or out_aggregate or cli'
python3 scripts/agent_loop.py preflight --task T-2026-0031 --from-git
git diff --check
make check-branch
```

## Session Handoff - 2026-05-29 KST

- Role: Implementer
- Lifecycle stage: implementation
- Branch / worktree: chore/issue-1667-t-2026-0031-parent-and-section-window-retrieval-experiment / current worktree
- Task: T-2026-0031
- Current status: active-loop gate repair and judge aggregate wiring are in progress; parent/window retrieval experiment is not yet claimed complete.
- Files touched: Makefile, scripts/agent_loop.py, tests/test_agent_loop.py, scripts/llm_judge.py, eval/judges/llm_judge.py, eval/run_eval.py, rag_synthesis.py, bidmate_data_boundary.py, ingestion.py, rag_indexing.py, docs/evaluation/surface-map.md, docs/private-real-eval-inventory.md, docs/operations/active-agent-loop.md, tasks/queue.md, real100_v2 checkpoint/baseline helper scripts and tests.
- Commands run: python3 -m py_compile scripts/agent_loop.py scripts/llm_judge.py eval/judges/llm_judge.py; python3 -m pytest -q tests/test_agent_loop.py -k 'active_auto_loop or make_active_start or active_codex_runner'; python3 -m pytest -q tests/test_llm_judge.py -k 'CLI or out_aggregate or cli'; make -n 시작; python3 scripts/agent_loop.py classify-surface --from-git.
- Results: focused active-loop tests passed; focused judge CLI tests passed; `make -n 시작` now shows max iterations 5, runner enabled, ship disabled, read-only sandbox, and no `--execute-ship`.
- Validation evidence: focused pytest and py_compile passed for the modified automation/judge surfaces; full gate validation still pending.
- Eval surface: eval-harness plus benchmark-reporting/product-runtime/ci-validation/docs-only; `real100_v2` aggregate-only evidence required before any retrieval or generation quality claim.
- Blockers: none for continuing automation repair; parent/window retrieval quality claim remains blocked on fresh paired `real100_v2` aggregate evidence.
- Open risks: changed-file surface is broad and includes data-boundary policy changes, so reviewer should check ADR/security implications before ship.
- Next action: rerun `preflight`, privacy audit, focused tests, and then `make 시작` to verify whether the loop can complete five locally gated tasks without ship.
- Next safe command: python3 scripts/agent_loop.py preflight --task T-2026-0031 --from-git
- Reviewer focus: task/branch alignment, no default ship path, gate-completion semantics, judge aggregate privacy boundary, external-egress policy.
