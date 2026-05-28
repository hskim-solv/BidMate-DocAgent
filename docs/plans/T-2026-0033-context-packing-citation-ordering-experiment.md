# Plan: T-2026-0033 context packing and citation ordering experiment

- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0033`
- Related issue / PR: [#1638](https://github.com/hskim-solv/BidMate-DocAgent/issues/1638) / PR TBD
- Related ADR: [ADR 0003](../adr/0003-structured-answer-citation-contract.md), [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0054](../adr/0054-conditional-on-answer-scorer-semantics.md)
- Created: 2026-05-28
- Last updated: 2026-05-28

## Problem Statement

`T-2026-0032` showed that local BGE-KO cross-encoder reranking is not a viable
near-term winner under the `T-2026-0030` latency hard ceiling. The next
candidate should improve how already-selected evidence is assembled for answer
generation while holding retrieval and reranker behavior fixed. Without a plan,
this can easily drift into retrieval ranking, query rewrite, prompt expansion,
or private raw-context reporting.

## Current Behavior

- `rag_core.py` retrieves and verifies evidence, then passes selected evidence
  into answer generation.
- `rag_answer.py` preserves the ADR 0003 answer dict contract and citation
  structure.
- `eval/run_eval.py` already reports answer, abstention, citation, latency, and
  synthesis token/cost fields when present.
- `reports/real100_v2/reranker_candidate_budget.aggregate.json` classifies the
  BGE-KO reranker screening as `latency_regression`; no reranker winner is
  available to promote.
- `reports/real100_v2/latency_cost_budget.aggregate.json` sets the current
  baseline hard no-go latency ceiling at 4799 ms and marks cost telemetry as
  not observable from the committed aggregate.

## Desired Behavior

Run an opt-in context-packing experiment that changes only the evidence assembly
fed to answer generation. The output should report aggregate-only deltas for
answer quality, citation guardrails, abstention, token/cost telemetry when
present, and latency. The experiment must explicitly classify whether citation
and answer metrics move together or whether any citation regression makes the
variant no-go.

## Constraints

- Scope constraints: experiment-only; no default runtime change.
- Architecture constraints: preserve ADR 0003 answer schema and ADR 0001
  baseline behavior.
- Compatibility constraints: additive variant/config/script/report only.
- Eval/privacy constraints: `real100_v2` only; aggregate-only committed output;
  no raw questions, answers, evidence, filenames, local paths, `doc_id`, or
  `chunk_id`.
- Tooling/CI constraints: CI may use a fixture/stub path; private run stays
  local and aggregate-only.
- Non-goals: retrieval ranking, reranker behavior, query rewrite, page metadata
  repair, and context length increase without token/latency budget.

## Architecture Impact

- Affected modules or docs: likely `scripts/`, `tests/`, `docs/evaluation/`,
  `reports/real100_v2/`, and `tasks/queue.md`.
- Affected contracts or invariants: ADR 0003 output contract unchanged; ADR 0005
  private boundary preserved.
- Load-bearing paths: no runtime paths unless a later implementation adds an
  opt-in answer/context variant.
- ADR required: no for an additive experiment; yes if a later PR changes default
  answer contract, retrieval, or context assembly behavior.
- Backward compatibility expectation: existing `agentic_full` and
  `naive_baseline` behavior remain unchanged unless the variant is explicitly
  selected.

## Affected Interfaces

- CLI/API/config: new or existing local experiment runner with explicit variant
  name such as `evidence_first`.
- Input data: ignored local `real100_v2` config/index/eval summaries.
- Output artifacts: aggregate-only JSON and Markdown report.
- Docs/review surfaces: plan, queue, sweep report, PR body §5b.
- Tests/eval entrypoints: focused unit tests plus private runner command.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: context-packing classification tied to matching `real100_v2`
  aggregate, latency/cost envelope, and unchanged retrieval/reranker behavior.
- Disallowed claim: global answer quality improvement, page citation readiness,
  or any comparison based on legacy `real100`/v1/221/kordoc evidence.
- Baseline or control affected: no default baseline change; paired control must
  be a matching `real100_v2` base aggregate.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Define the context-packing matrix: evidence-first ordering, duplicate
   suppression, conflict grouping, and final context budget.
2. Implement or reuse an opt-in local runner that compares control vs variant
   without changing retrieval, reranking, verifier, or answer schema defaults.
3. Emit aggregate-only metrics for answer quality, citation precision/alignment,
   abstention, token/cost when present, latency, and no-go classification.
4. Render a reviewer-facing report and update queue handoff with the next
   decision.
5. Run benchmark/privacy/claim audits before PR.

## Acceptance Criteria

- [ ] Context assembly variant is opt-in and separately named.
- [ ] Retrieval and reranker behavior are explicitly unchanged in the aggregate.
- [ ] Citation and answer metrics move together; citation regression is no-go.
- [ ] Token/cost status is reported as present, absent, or not applicable.
- [ ] No legacy `real100`/v1/221/kordoc evidence is used.

## Validation Strategy

Commands that must be run by the implementation PR:

```bash
python3 -m pytest -q tests/test_answer_contract_snapshot.py <focused-context-tests>
python3 <context-packing-experiment> --config <local-v2-config> --index-dir <local-v2-index> --variant evidence_first --out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <real100_v2-variant-aggregate>
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md <report-path>
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests and local private context-packing command pass.
- Generated or updated artifact: aggregate-only context-packing report.
- Reviewer checklist or manual inspection: answer contract, citation guardrail,
  latency/cost, and privacy checks pass.
- Explicitly not validated, with reason: no default runtime improvement unless
  paired private delta and latency/cost guardrail support it.

## Rollback Strategy

Revert the experiment runner/report/config additions. Do not delete local
private `real100_v2` raw run artifacts or indexes during rollback.

## Failure Modes

- Failure mode: answer quality improves while citation precision or
  claim-citation alignment regresses.
- Detection signal: report classifies the variant as citation no-go.
- Stop condition or fallback: do not claim improvement; tighten context
  selection or abandon the variant.

- Failure mode: variant increases token count or latency beyond the budget.
- Detection signal: token/cost block or latency budget reports a no-go breach.
- Stop condition or fallback: reduce context budget or keep control behavior.

- Failure mode: raw private fields leak into aggregate output.
- Detection signal: privacy audit or focused test fails.
- Stop condition or fallback: strip to closed enums/counts only.

## Observability

- `reports/real100_v2/latency_cost_budget.aggregate.json`
- `reports/real100_v2/reranker_candidate_budget.aggregate.json`
- Future context-packing aggregate and Markdown report
- `make real-eval-v2-guard`
- `python3 scripts/agent_loop.py privacy-audit-output`
- `python3 scripts/agent_loop.py claim-audit --from-git`

## Reviewer Notes

Attack citation regressions and scope drift first. This experiment is only
useful if retrieval/reranking stay fixed and answer/citation metrics improve
together within the latency/cost budget.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 12:55 KST

- Role: Planner
- Branch / worktree: eval/issue-1638-plan-context-packing-citation-ordering-experimen / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1638 / PR TBD
- Task: T-2026-0033
- Current status: plan drafted; implementation should add an opt-in context-packing runner/report.
- Files touched: docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md, tasks/queue.md, scripts/check_real100_v2_only.py
- Decisions made: next experiment holds retrieval/reranking fixed because T-2026-0032 found local BGE-KO reranker latency no-go; no claim without paired real100_v2 aggregate and citation guardrails.
- Commands run: make ship-start TITLE="Plan context packing citation ordering experiment" TYPE=eval; make check-branch.
- Results: issue #1638 and branch created; branch gate passed; plan drafted.
- Next safe command: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md
- Open questions: none.
- Risks: implementation can drift into retrieval/reranker/query rewrite unless the variant boundary is kept explicit.
```
