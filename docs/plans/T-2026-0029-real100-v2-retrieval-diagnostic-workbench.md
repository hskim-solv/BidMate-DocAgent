# Plan: T-2026-0029 real100_v2 retrieval diagnostic workbench

- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0029`
- Related issue / PR: [#1622](https://github.com/hskim-solv/BidMate-DocAgent/issues/1622), reopened follow-up [#1764](https://github.com/hskim-solv/BidMate-DocAgent/issues/1764)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0076](../adr/0076-multi-chunk-evidence-failure-analysis-surface.md)
- Created: 2026-05-28
- Last updated: 2026-06-02

## Problem Statement

`real100_v2` is now the only valid private eval surface, but the next retrieval
step is not yet explainable enough to choose between candidate-pool expansion,
same-document/window work, or follow-up query decomposition. The current
baseline packet reports top-line metrics and a page metadata blocker, but it
does not provide a compact aggregate diagnostic that separates not-in-pool,
ranked-too-low, duplicate, metadata-filter, verifier, label, and multi-evidence
failure buckets for reviewers.

## Current Behavior

`reports/real100_v2/baseline.aggregate.json` is aggregate-only and commit-safe,
but per-case retrieval failure categorization exists only in ignored private
`reports/real100_v2/eval_summary.json`. Older multi-chunk scripts default to
`reports/real100/` and are archive-only for this task. They cannot be used as
current evidence under the v2-only policy from T-2026-0028.

The known `real100_v2` page metadata ready rate is 0.0, so page/citation claims
remain blocked. Diagnostic work may carry this blocker forward but must not
replace it with legacy `real100`/v1/221/kordoc evidence.

## Desired Behavior

Add a read-only renderer that consumes local private `real100_v2` eval summary
rows and emits only aggregate JSON/Markdown. The report should make the next
retrieval decision observable without exposing raw private text, document IDs,
chunk IDs, filenames, or local paths.

## Constraints

- Scope constraints: diagnostic/reporting only.
- Architecture constraints: no runtime retrieval, reranking, verifier, answer,
  ingestion, chunking, or eval scoring behavior changes.
- Compatibility constraints: no CLI contract removal; new script is additive.
- Eval/privacy constraints: `real100_v2` only; aggregate-only committed output.
- Tooling/CI constraints: keep local command runnable without external services.
- Non-goals: page metadata repair, retrieval behavior change, performance claim.

## Architecture Impact

- Affected modules or docs: `scripts/`, `tests/`, `reports/real100_v2/`,
  `docs/evaluation/`, `tasks/queue.md`.
- Affected contracts or invariants: private raw artifacts stay ignored; v2-only
  evidence policy is preserved.
- Load-bearing paths: none.
- ADR required: no; this is an additive diagnostic surface under existing
  eval/privacy ADRs.
- Backward compatibility expectation: existing commands and reports continue to
  work.

## Affected Interfaces

- CLI/API/config: new renderer CLI only.
- Input data: ignored local `reports/real100_v2/eval_summary.json`.
- Output artifacts: aggregate JSON and Markdown report.
- Docs/review surfaces: queue, plan, report, real100_v2 README.
- Tests/eval entrypoints: focused pytest plus v2 guard.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: diagnostic bucket counts and next-task recommendation based on
  the specific v2 aggregate.
- Disallowed claim: performance improvement, page/citation readiness, or any
  conclusion based on legacy `real100`/v1/221/kordoc evidence.
- Baseline or control affected: no; read-only renderer.
- Benchmark/eval auditor required: yes.

### 2026-06-02 page-aware re-measurement (issue #1764)

The diagnostic was rerun (diagnostic-only) against the MiniLM page-aware
`real100_v2` index (`real100_v2_checkpoint_minilm_pageaware`) after the naive
baseline remeasurement reopened this task. Findings:

- Page-span blocker resolved: `page_metadata_blocker.status` flipped
  `blocked_for_page_and_window_claims` -> `available`, coverage 0.0 -> 1.0
  (24613/24613 chunks). This unblocks T-2026-0031 for follow-up.
- Doc-level retrieval regressed sharply versus the prior hashing-backed
  `real100_v2` run: gold documents in per-case retrieved 61.4% -> 12.1%, gold
  chunk-ids 44.1% -> 1.1%, while the retrieved document universe still contained
  88.3% of gold documents (answerable-with-gold population, matching the 12.1%
  denominator; 91.7% across all cases). This is a per-query retrieval/ranking collapse, not a
  missing-index problem (this is an ALLOWED paired comparison — both sides are
  `real100_v2`, no legacy `real100`/v1/221/kordoc evidence).
- Renderer hardening (additive, no runtime behavior change): BUG #1 made the
  page-blocker prose dynamic (was hardcoded "ready rate is 0.0"); BUG #2 added a
  candidate-pool-collapse gate to `_recommend_next_task` that emits a
  `retrieval_integrity_suspect` signal pointing at T-2026-0076 when gold is
  observed in <5% of answerable cases, instead of recommending the reranker
  (T-2026-0032) which only helps when gold IS in the pool but ranked low.
- Root-cause investigation (query/index embedding parity + a missing
  embedding/retrieval-backend provenance field in `eval_summary`) is spun off as
  the new queue task T-2026-0076; NOT implemented in this PR.
- Carry-forward caveat: `real100_v2` `eval_summary` has no embedding/retrieval-backend
  provenance field, so query<->index embedding parity is unverified.

## Task Breakdown

1. Add `scripts/render_real100_v2_retrieval_diagnostics.py`.
2. Add focused tests for bucket classification, privacy boundary, and fail-closed
   legacy input handling.
3. Render aggregate JSON/Markdown from the canonical private `real100_v2`
   summary.
4. Update queue, README, and guard coverage so the next task can proceed from
   current v2 evidence.

## Acceptance Criteria

- [x] Diagnostics distinguish not-in-candidate-pool, ranked-too-low,
  boundary/window, duplicate, metadata-filter, and multi-evidence failures.
- [x] Output is aggregate-only and commit-safe.
- [x] The report can decide whether `T-2026-0031` or `T-2026-0032` is the next
  best experiment.
- [x] The report explicitly carries forward the v2 page metadata blocker and
  does not use old `real100` evidence as a substitute.

## Validation Strategy

Commands that must be run:

```bash
python3 -m py_compile scripts/render_real100_v2_retrieval_diagnostics.py scripts/check_real100_v2_only.py
python3 -m pytest -q tests/test_render_real100_v2_retrieval_diagnostics.py tests/test_real100_v2_guard.py tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent python3 scripts/render_real100_v2_retrieval_diagnostics.py
make real-eval-v2-guard
bash -n .githooks/pre-commit
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md docs/evaluation/real100_v2-retrieval-diagnostics.md reports/real100_v2/README.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests pass.
- Generated or updated artifact: `reports/real100_v2/retrieval_diagnostics.aggregate.json`,
  `docs/evaluation/real100_v2-retrieval-diagnostics.md`.
- Reviewer checklist or manual inspection: privacy and claim audits pass.
- Explicitly not validated, with reason: no retrieval performance delta because
  runtime behavior does not change.

## Rollback Strategy

Revert the renderer, tests, report, and queue/doc updates. Do not delete local
private `real100_v2` raw summaries or indexes during rollback.

## Failure Modes

- Failure mode: renderer accidentally accepts legacy `real100` input.
- Detection signal: focused test and `make real-eval-v2-guard` fail.
- Stop condition or fallback: stop before PR and tighten input path checks.

- Failure mode: aggregate output leaks raw identifiers or local paths.
- Detection signal: privacy test or agent-loop privacy audit fails.
- Stop condition or fallback: strip fields to closed enums/counts only.

- Failure mode: report reads page metadata blocker as solved.
- Detection signal: claim audit or report review flags page readiness language.
- Stop condition or fallback: reword as no-go blocker for page/citation claims.

## Observability

- `reports/real100_v2/retrieval_diagnostics.aggregate.json`
- `docs/evaluation/real100_v2-retrieval-diagnostics.md`
- `make real-eval-v2-guard`
- `python3 scripts/agent_loop.py privacy-audit-output`
- `python3 scripts/agent_loop.py claim-audit --from-git`

## Reviewer Notes

Attack privacy boundary first, then claim wording. This PR must not change
runtime behavior and must not cite legacy `real100`/v1/221/kordoc evidence as
current support.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 09:20 KST

- Role: Implementer
- Branch / worktree: eval/issue-1622-build-real100-v2-retrieval-diagnostic-workbench / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1622 / PR TBD
- Task: T-2026-0029
- Current status: real100_v2 retrieval diagnostics rendered and ready for review.
- Files touched: .gitignore, .githooks/pre-commit, scripts/render_real100_v2_retrieval_diagnostics.py, scripts/check_real100_v2_only.py, tests/test_render_real100_v2_retrieval_diagnostics.py, docs/evaluation/real100_v2-retrieval-diagnostics.md, reports/real100_v2/retrieval_diagnostics.aggregate.json, reports/real100_v2/README.md, docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md, tasks/queue.md
- Decisions made: use only real100_v2 local summary as raw input and emit aggregate-only committed artifacts.
- Commands run: make ship-start TITLE="Build real100 v2 retrieval diagnostic workbench" TYPE=eval; make check-branch; python3 scripts/agent_loop.py next; REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent python3 scripts/render_real100_v2_retrieval_diagnostics.py; python3 -m py_compile scripts/render_real100_v2_retrieval_diagnostics.py scripts/check_real100_v2_only.py; python3 -m pytest -q tests/test_render_real100_v2_retrieval_diagnostics.py tests/test_real100_v2_guard.py tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py; make real-eval-v2-guard; bash -n .githooks/pre-commit; python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md docs/evaluation/real100_v2-retrieval-diagnostics.md reports/real100_v2/README.md; python3 scripts/agent_loop.py privacy-audit-output; python3 scripts/agent_loop.py claim-audit --from-git.
- Results: renderer generated aggregate JSON/Markdown; focused tests, v2 guard, hook syntax check, doc links, privacy audit, and claim audit passed.
- Next safe command: git diff --check && make check-branch
- Open questions: none.
- Risks: duplicate/near-duplicate signal counts repeated top documents as aggregate near-duplicates, not semantic duplicates.
```
