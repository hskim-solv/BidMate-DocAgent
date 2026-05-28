# Plan: T-2026-0030 real100_v2 latency and cost budget envelope

- Status: review
- Owner role: Implementer -> CI Reviewer -> Benchmark Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0030`
- Related issue / PR: [#1626](https://github.com/hskim-solv/BidMate-DocAgent/issues/1626)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-28
- Last updated: 2026-05-28

## Problem Statement

`T-2026-0032` needs a latency/cost guardrail before a reranker candidate-budget
experiment can make any quality claim. Without a shared envelope, a future PR
could report retrieval quality gains while hiding local reranker latency or
missing paid/API cost evidence.

## Current Behavior

`reports/real100_v2/baseline.aggregate.json` already contains aggregate p50,
p95, mean latency and stage latency for the current private baseline. It does
not expose p99, synthesis token totals, or synthesis cost totals in the
committed aggregate.

## Desired Behavior

Create a committed aggregate-only budget packet that names p50, p95, p99
status, stage-level latency, soft ceilings, hard no-go ceilings, cost evidence
availability, warm/cold caveats, and downstream no-go rules.

## Constraints

- Scope constraints: measurement/reporting only.
- Architecture constraints: no runtime retrieval, reranking, verifier, answer,
  ingestion, chunking, or eval scoring behavior changes.
- Compatibility constraints: additive script/report only.
- Eval/privacy constraints: `real100_v2` committed aggregate only; no raw
  private rows or identifiers.
- Tooling/CI constraints: report must be reproducible from committed aggregate.
- Non-goals: latency optimization, production SLO, paired quality delta.

## Architecture Impact

- Affected modules or docs: `scripts/`, `tests/`, `docs/evaluation/`,
  `reports/real100_v2/`, `tasks/queue.md`.
- Affected contracts or invariants: ADR 0005 private boundary and v2-only
  evidence policy.
- Load-bearing paths: none.
- ADR required: no; this is additive reporting.
- Backward compatibility expectation: existing eval/runtime behavior unchanged.

## Affected Interfaces

- CLI/API/config: new renderer CLI only.
- Input data: `reports/real100_v2/baseline.aggregate.json`.
- Output artifacts: `reports/real100_v2/latency_cost_budget.aggregate.json` and
  `docs/evaluation/real100_v2-latency-cost-budget.md`.
- Docs/review surfaces: plan, queue, report, README.
- Tests/eval entrypoints: focused renderer tests and doc/guard checks.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: latency/cost guardrail derived from the current committed
  `real100_v2` aggregate.
- Disallowed claim: production SLO, performance improvement, or
  legacy `real100`/v1/221/kordoc comparison.
- Baseline or control affected: no.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Add `scripts/render_real100_v2_latency_budget.py`.
2. Add focused tests for budget math, privacy boundary, and legacy input
   rejection.
3. Render aggregate JSON and Markdown budget report.
4. Allowlist the new aggregate artifact and update queue/README/guard coverage.

## Acceptance Criteria

- [x] Budget report names p50, p95, p99 status, and stage-level components.
- [x] Candidate-pool, reranker, query-rewrite, and context-packing tasks can cite
  the same latency/cost envelope.
- [x] The report states warm/cold and local hardware caveats.
- [x] Cost evidence availability is explicit and quality-only gains are no-go.

## Validation Strategy

Commands that must be run:

```bash
python3 -m py_compile scripts/render_real100_v2_latency_budget.py scripts/check_real100_v2_only.py
python3 -m pytest -q tests/test_render_real100_v2_latency_budget.py tests/test_real100_v2_guard.py
python3 scripts/render_real100_v2_latency_budget.py
make real-eval-v2-guard
bash -n .githooks/pre-commit
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md docs/evaluation/real100_v2-latency-cost-budget.md reports/real100_v2/README.md
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests pass.
- Generated or updated artifact: latency/cost aggregate JSON and Markdown.
- Reviewer checklist or manual inspection: privacy and claim audits pass.
- Explicitly not validated, with reason: no paired delta because runtime
  behavior does not change.

## Rollback Strategy

Revert the renderer, tests, allowlist entries, report, and queue/doc updates.
Do not delete private raw `real100_v2` runs or indexes during rollback.

## Failure Modes

- Failure mode: a future quality-only experiment cites the budget as a success
  claim.
- Detection signal: claim audit or reviewer sees no paired delta.
- Stop condition or fallback: classify as no-go until paired quality and
  latency/cost evidence exist.

- Failure mode: cost is missing but treated as zero.
- Detection signal: report status is `not_observable_from_committed_aggregate`.
- Stop condition or fallback: require explicit not-applicable or fresh aggregate
  with cost fields.

## Observability

- `reports/real100_v2/latency_cost_budget.aggregate.json`
- `docs/evaluation/real100_v2-latency-cost-budget.md`
- `make real-eval-v2-guard`
- `python3 scripts/agent_loop.py privacy-audit-output`
- `python3 scripts/agent_loop.py claim-audit --from-git`

## Reviewer Notes

Attack the no-go wording first. This PR should make it harder, not easier, to
claim a quality win without latency and cost evidence.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 10:15 KST

- Role: Implementer
- Branch / worktree: eval/issue-1626-define-real100-v2-latency-and-cost-budget-envelo / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1626 / PR TBD
- Task: T-2026-0030
- Current status: latency/cost budget report rendered and ready for review.
- Files touched: .gitignore, .githooks/pre-commit, scripts/render_real100_v2_latency_budget.py, tests/test_render_real100_v2_latency_budget.py, docs/evaluation/real100_v2-latency-cost-budget.md, reports/real100_v2/latency_cost_budget.aggregate.json, reports/real100_v2/README.md, docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md, tasks/queue.md
- Decisions made: p99 and cost are not observable from the committed aggregate; quality-only gains are no-go unless cost is present or explicitly not applicable.
- Commands run: make ship-start TITLE="Define real100 v2 latency and cost budget envelope" TYPE=eval; make check-branch; python3 scripts/render_real100_v2_latency_budget.py; python3 -m pytest -q tests/test_render_real100_v2_latency_budget.py.
- Results: issue #1626 and branch created; renderer generated aggregate JSON/Markdown; focused tests passed.
- Next safe command: python3 -m py_compile scripts/render_real100_v2_latency_budget.py scripts/check_real100_v2_only.py && python3 -m pytest -q tests/test_render_real100_v2_latency_budget.py tests/test_real100_v2_guard.py
- Open questions: none.
- Risks: p99 and cost are named but not available in the current committed source aggregate.
```
