# Plan: T-2026-0032 reranker candidate-budget experiment

- Status: proposed
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0032`
- Related issue / PR: [#1624](https://github.com/hskim-solv/BidMate-DocAgent/issues/1624)
- Related ADR: [ADR 0001](../adr/0001-preserve-naive-baseline.md), [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0026](../adr/0026-cross-encoder-reranker-deferral.md)
- Created: 2026-05-28
- Last updated: 2026-05-28

## Problem Statement

`T-2026-0029` selected `T-2026-0032` as the next experiment candidate because
`T-2026-0031` remains blocked by `real100_v2` page metadata coverage 0.0.
However, a reranker candidate-budget sweep can easily trade quality for latency
or hide candidate-pool recall failures. The experiment needs a fixed plan that
separates candidate-pool recall from reranker precision and refuses headline
claims without the latency/cost guardrail from `T-2026-0030`.

## Current Behavior

The repo already has a cross-encoder reranker surface:

- `rag_reranker.py` exposes the `Reranker` protocol and default
  `CrossEncoderReranker`.
- `rag_retrieval.py` applies reranking before the final `top_k` cut when the
  plan enables rerank.
- `eval/run_eval.py` aggregates `rerank_delta_mrr`, `rerank_delta_ndcg_at_10`,
  `reranker_backend`, stage latency, and run config provenance.
- `docs/retrieval/cross-encoder-reranker.md` documents the existing backend
  choices and the historical synthetic finding that reranker quality gains must
  be treated carefully.
- `reports/real100_v2/retrieval_diagnostics.aggregate.json` shows the current
  v2 diagnostic trigger: dominant exclusive retrieval status is
  `not_observable_limited_depth`, page metadata coverage is 0.0, and
  `T-2026-0032` is preferred while `T-2026-0031` is blocked.

## Desired Behavior

Run an opt-in private `real100_v2` candidate-budget sweep that compares
candidate pool settings and reranker top-N limits without changing default
runtime behavior. The output should classify the result as winner,
recall-only gain, ranking regression, citation regression, latency regression,
or failed experiment.

## Constraints

- Scope constraints: experiment-only; no default runtime change.
- Architecture constraints: preserve ADR 0001 `naive_baseline`; do not mix
  reranking with query rewrite, parent expansion, or context packing.
- Compatibility constraints: additive config/script/report only.
- Eval/privacy constraints: `real100_v2` only; aggregate-only committed output;
  no raw questions, answers, evidence, filenames, local paths, `doc_id`, or
  `chunk_id`.
- Tooling/CI constraints: local reranker dependencies must be explicit; CI may
  use stub backend only.
- Non-goals: page metadata repair, LLM reranking, production default flip,
  improvement claim without paired private aggregate delta.

## Architecture Impact

- Affected modules or docs: likely `scripts/`, `tests/`, `docs/evaluation/`,
  `reports/real100_v2/`, and `tasks/queue.md`.
- Affected contracts or invariants: ADR 0001 baseline unchanged; ADR 0005
  private boundary preserved.
- Load-bearing paths: no runtime paths unless a later implementation adds an
  opt-in eval runner under `eval/`.
- ADR required: no for an additive experiment; yes if a later PR changes default
  retrieval or reranker behavior.
- Backward compatibility expectation: existing `full_reranker` and stub backend
  behavior remain unchanged.

## Affected Interfaces

- CLI/API/config: new or existing local experiment runner with explicit backend,
  candidate budget, and top-N options.
- Input data: ignored local `real100_v2` config/index/eval summaries.
- Output artifacts: aggregate-only sweep JSON/Markdown.
- Docs/review surfaces: plan, queue, sweep report, PR body §5b.
- Tests/eval entrypoints: focused unit tests plus private runner command.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: experiment classification tied to a specific v2 paired
  aggregate and latency/cost envelope.
- Disallowed claim: global reranker improvement, page/citation readiness, or any
  comparison based on legacy `real100`/v1/221/kordoc evidence.
- Baseline or control affected: no default baseline change; paired control must
  be a matching `real100_v2` base aggregate.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Complete or cite `T-2026-0030` latency/cost budget envelope before treating a
   reranker run as PR-ready evidence.
2. Define candidate budget matrix: retriever candidate count, reranker top-N,
   final `top_k`, backend/model, and expected local dependency.
3. Implement or reuse a local runner that emits paired aggregate outputs without
   raw private fields.
4. Render a reviewer-facing report that separates candidate-pool recall from
   reranker precision and classifies the result.
5. Run benchmark/privacy/claim audits before PR.

## Acceptance Criteria

- [ ] Sweep output classifies winner, recall-only gain, ranking regression,
  citation regression, latency regression, or failed experiment.
- [ ] Candidate-pool recall and reranker precision are reported separately.
- [ ] Reranker provenance is present in aggregate output.
- [ ] Latency/cost guardrail from `T-2026-0030` is present or this task remains
  blocked.
- [ ] No legacy `real100`/v1/221/kordoc evidence is used.

## Validation Strategy

Commands that must be run by the implementation PR:

```bash
python3 -m pytest -q tests/test_reranker*.py <focused-new-tests>
python3 <reranker-sweep-script> --config <local-v2-config> --out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <real100_v2-variant-aggregate>
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md <report-path>
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests and local private sweep command pass.
- Generated or updated artifact: aggregate-only sweep report.
- Reviewer checklist or manual inspection: benchmark validity, latency/cost, and
  privacy checks pass.
- Explicitly not validated, with reason: no default runtime improvement unless
  paired private delta and latency/cost guardrail support it.

## Rollback Strategy

Revert the experiment runner/report/config additions. Do not delete local
private `real100_v2` raw run artifacts or indexes during rollback.

## Failure Modes

- Failure mode: reranker appears to improve top-line quality but candidate-pool
  recall falls.
- Detection signal: report classifies `recall_only_gain` or
  `ranking_regression` rather than `winner`.
- Stop condition or fallback: do not claim improvement; move to candidate-pool
  or retrieval-depth work.

- Failure mode: latency/cost guardrail is missing.
- Detection signal: no `T-2026-0030` envelope in the report.
- Stop condition or fallback: keep T-2026-0032 blocked and run T-2026-0030.

- Failure mode: raw private fields leak into aggregate output.
- Detection signal: privacy audit or focused test fails.
- Stop condition or fallback: strip to closed enums/counts only.

## Observability

- `reports/real100_v2/retrieval_diagnostics.aggregate.json`
- Future sweep aggregate and Markdown report
- `rerank_delta_mrr`, `rerank_delta_ndcg_at_10`, `retrieval_metrics`, and
  `stage_latency`
- `make real-eval-v2-guard`
- `python3 scripts/agent_loop.py privacy-audit-output`
- `python3 scripts/agent_loop.py claim-audit --from-git`

## Reviewer Notes

Attack the claim wording first. A reranker experiment is not a success if it
wins only by hiding candidate-pool recall, regresses citation behavior, or
exceeds the latency/cost envelope.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 09:55 KST

- Role: Planner
- Branch / worktree: eval/issue-1624-plan-reranker-candidate-budget-experiment / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1624 / PR TBD
- Task: T-2026-0032
- Current status: plan drafted; implementation should wait for or include T-2026-0030 latency/cost guardrail.
- Files touched: docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md
- Decisions made: no reranker claim without paired real100_v2 delta and latency/cost envelope; legacy real100/v1/221/kordoc evidence remains banned.
- Commands run: make ship-start TITLE="Plan reranker candidate budget experiment" TYPE=eval; make check-branch; python3 scripts/agent_loop.py next.
- Results: issue #1624 and branch created; branch gate passed; next task is T-2026-0032.
- Next safe command: update tasks/queue.md to link this plan and mark the T-2026-0030 dependency explicitly.
- Open questions: none.
- Risks: implementing the sweep before a latency/cost envelope would produce unusable review evidence.
```
