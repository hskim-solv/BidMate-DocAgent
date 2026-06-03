# Plan: T-2026-0005 Multi-chunk evidence regression guard

- Status: review
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0005`
- Related issue / PR: #1484 / #1491
- Related ADR: [ADR 0001](../adr/0001-preserve-naive-baseline.md), [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0058](../adr/0058-phase35-mode-winner.md), [ADR 0076](../adr/0076-multi-chunk-evidence-failure-analysis-surface.md)
- Created: 2026-05-25
- Last updated: 2026-06-04

## Problem Statement

Recent multi-chunk evidence work produced aggregate-only `real100_v2`
private-eval reports, but the next executable step needs a small regression
guard that does not require private raw data or retrieval behavior changes.

Without this guard, future retrieval work can claim progress on multi-chunk failures without a public, repeatable signal that distinguishes all-gold hits, partial same-document hits, and distractor-only top-k failures.

## Current Behavior

- `scripts/render_multi_chunk_evidence_failures.py` summarizes current
  `real100_v2` private-eval multi-chunk failures as aggregate counts only.
- `docs/evaluation/multi_chunk_retrieval_strategy.md` recommends deferring concrete retrieval changes until page metadata recovery because the private aggregate has unknown same-doc vs multi-doc split.
- `eval/naive_rag/benchmark.py` runs the public synthetic Naive RAG benchmark and records retrieval/citation/answer metrics, but the metrics payload does not expose a dedicated multi-chunk evidence retrieval profile.
- The public synthetic benchmark already has `multi_chunk_synthesis` questions with explicit multi-chunk gold evidence.

## Desired Behavior

Add a public synthetic benchmark regression profile that classifies multi-chunk evidence cases by top-10 retrieval outcome and failure mode. The profile is additive, public, and does not change retrieval, scoring, answer, verifier, or baseline behavior.

## Constraints

- Scope constraints: only add the first regression guard; do not implement same-document candidate expansion.
- Architecture constraints: no retrieval architecture rewrite and no default `retrieval_mode` change.
- Compatibility constraints: additive metrics payload field only; existing metrics semantics remain unchanged.
- Eval/privacy constraints: surface is public synthetic benchmark; do not use private raw data.
- Tooling/CI constraints: keep validation to focused pytest, py_compile, and diff check.
- Non-goals: no quality improvement claim, no current `real100_v2`
  private-eval delta, no benchmark score change.

## Architecture Impact

- Affected modules or docs: `eval/naive_rag/benchmark.py`, focused benchmark tests, plan handoff.
- Affected contracts or invariants: `naive_baseline` ranking and retrieval backend remain unchanged.
- Load-bearing paths: `eval/` is load-bearing; this is metrics reporting only.
- ADR required: no; this extends an existing public synthetic benchmark output with an additive field and does not introduce a new measurement surface.
- Backward compatibility expectation: existing benchmark consumers can ignore the new field.

## Affected Interfaces

- CLI/API/config: none.
- Input data: no new input.
- Output artifacts: benchmark `metrics.json` gains `multi_chunk_evidence_profile`.
- Docs/review surfaces: plan handoff only.
- Tests/eval entrypoints: `tests/test_naive_rag_benchmark_v1.py`.

## Data / Eval Impact

- Surface: public synthetic benchmark.
- Data boundary: public synthetic data only.
- Allowed claim: "synthetic v1 benchmark now reports a multi-chunk evidence regression profile."
- Disallowed claim: "retrieval quality improved" or any real-world/current
  `real100_v2` private-eval performance claim.
- Baseline or control affected: no; retrieval calls and scoring are unchanged.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Add aggregate multi-chunk evidence profile helpers to `eval/naive_rag/benchmark.py`.
2. Wire the profile into benchmark `metrics.json` without changing existing metrics.
3. Add focused tests for same-doc partial hit and cross-document distractor buckets.
4. Run focused validation and update handoff.

## Acceptance Criteria

- [x] Benchmark metrics include `multi_chunk_evidence_profile` with closed bucket counts.
- [x] Tests cover same-document single-gold partial hit and cross-document distractor-only failure modes.
- [x] Focused validation passes or failures are reported with scope.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py
python3 -m py_compile scripts/render_multi_chunk_evidence_failures.py rag_retrieval.py rag_core.py eval/naive_rag/benchmark.py
git diff --check
```

Expected evidence:

- Test/eval output: focused pytest pass.
- Generated or updated artifact: none committed.
- Reviewer checklist or manual inspection: Normal, adversarial, benchmark validity, and regression checks.
- Explicitly not validated, with reason: current `real100_v2` private eval
  not run because this is public synthetic benchmark reporting only.

## Rollback Strategy

Revert the benchmark helper, metrics payload field, and focused tests. No private artifacts or benchmark datasets need deletion.

## Failure Modes

- Failure mode: profile changes retrieval/scoring behavior.
- Detection signal: diff shows changed `run_rag_query` arguments or metric computations for existing keys.
- Stop condition or fallback: revert to tests-only guard.

- Failure mode: profile is read as quality improvement.
- Detection signal: docs/final wording claims performance gain.
- Stop condition or fallback: restrict wording to public synthetic regression observability.

## Observability

- `metrics.json::multi_chunk_evidence_profile`
- `tests/test_naive_rag_benchmark_v1.py`
- Focused pytest and py_compile output.

## Reviewer Notes

Attack claim wording, additive-only output shape, baseline preservation, and whether the bucket names overstate mitigation.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-25 23:45 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: stacked draft PR preparation
- Branch / worktree: eval/issue-1484-multi-chunk-evidence-profile / /Users/hskim/.codex/worktrees/1484/BidMate-DocAgent
- Base branch: fix/issue-1485-benchmark-integrity-followup (#1488)
- Issue / PR: #1484 / #1491
- Task: T-2026-0005
- Plan: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Current status: split from the mixed integration worktree onto a stacked issue-linked branch based on #1488; focused validation passed and draft PR #1491 is open.
- Files touched: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md, eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: stack this PR on #1488 because both changes touch `eval/naive_rag/benchmark.py` and `tests/test_naive_rag_benchmark_v1.py`; keep this checkpoint additive and observability-only.
- Commands run: git worktree add -b eval/issue-1484-multi-chunk-evidence-profile /Users/hskim/.codex/worktrees/1484/BidMate-DocAgent origin/fix/issue-1485-benchmark-integrity-followup; git diff origin/fix/issue-1485-benchmark-integrity-followup -- eval/naive_rag/benchmark.py tests/test_naive_rag_benchmark_v1.py | git -C /Users/hskim/.codex/worktrees/1484/BidMate-DocAgent apply; git diff --no-index ... plan copy via mktemp + git apply; python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py; python3 -m py_compile scripts/render_multi_chunk_evidence_failures.py rag_retrieval.py rag_core.py eval/naive_rag/benchmark.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch; python3 -m eval.naive_rag.benchmark --config configs/eval/benchmark_naive_rag_v1.yaml --run-id integration-profile-check --output-root "$tmpdir".
- Results: branch split completed; all listed validation commands exited 0; draft PR #1491 opened. Observed public fixture profile: case_count=7, same_doc=7, all_gold_retrieved=6, partial_gold_retrieved=1, top10_failure_count=1, top10_not_observable_count=0.
- Validation evidence: focused pytest passed; py_compile passed; doc link check reported no broken links; diff check passed; benchmark entrypoint generated `multi_chunk_evidence_profile` under a mktemp output directory.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: none.
- Blockers: none.
- Open risks: stacked PR depends on #1488; wording must remain public synthetic benchmark observability only, not retrieval quality improvement.
- Next action: review stacked draft PR #1491 after #1488, then retarget/rebase as needed.
- Next safe command: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py
- Reviewer focus: additive-only metrics payload, current fixture bucket
  assertions, no retrieval/scoring behavior drift, no current `real100_v2`
  private-eval or performance claim.

## Session Handoff - 2026-05-26 14:03 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: merge preparation
- Branch / worktree: eval/issue-1484-multi-chunk-evidence-profile / /Users/hskim/.codex/worktrees/1484/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1484 / #1491
- Task: T-2026-0005
- Current status: #1488 merged, #1491 retargeted to main, review-gate blocker addressed.
- Files touched: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md, eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: empty retrieval is classified as `retrieval_outcome_at_10=no_gold_retrieved`; its `top10_failure_mode` remains `not_observable` because no retrieved document evidence can distinguish same-document vs cross-document distractor modes.
- Commands run: git fetch origin main; git merge --no-edit origin/main; python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py; python3 -m py_compile scripts/render_multi_chunk_evidence_failures.py rag_retrieval.py rag_core.py eval/naive_rag/benchmark.py; git diff --check; gh pr edit 1491 --base main; gh pr checks 1491 --watch --interval 10; make ship-review-gate PR=1491.
- Results: retargeted CI passed; review gate then found one unresolved thread; code/test updated to address the empty retrieval bucket; focused pytest, py_compile, and diff check passed after the fix.
- Validation evidence: focused pytest passed; py_compile passed; diff check passed.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: none.
- Blockers: pending push and final PR CI rerun after review fix.
- Open risks: final CI must pass again before merge; no current `real100_v2`
  private-eval or retrieval quality claim should be made.
- Next action: push review fix, wait for #1491 CI, rerun review gate, then squash merge if clean.
- Next safe command: gh pr checks 1491 --watch --interval 10

## Session Handoff - 2026-05-25 19:44 KST

- Role: Planner -> Implementer
- Branch / worktree: dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Issue / PR: N/A
- Task: T-2026-0005
- Current status: running
- Files touched: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Decisions made: Do not change retrieval behavior; add public synthetic benchmark regression profile only.
- Commands run: date '+%Y-%m-%d %H:%M %Z'
- Results: timestamp captured for handoff.
- Next safe command: implement profile helper in eval/naive_rag/benchmark.py.
- Open questions: none.
- Risks: existing unrelated local changes in eval/naive_rag/validate_benchmark_dataset.py and docs/plans/T-2026-0001-benchmark-integrity-followup.md must not be overwritten.
```

```markdown
## Session Handoff - 2026-05-25 19:49 KST

- Role: Planner -> Implementer
- Lifecycle stage: review
- Branch / worktree: dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Base branch: origin/main
- Issue / PR: N/A / PR TBD
- Task: T-2026-0005
- Plan: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Current status: additive benchmark profile implemented and focused validation passed.
- Files touched: eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py, tasks/queue.md, docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Decisions made: add a public synthetic benchmark profile only; no retrieval,
  verifier, scoring, dataset, or current `real100_v2` private-eval changes.
- Commands run: python3 -m pytest -q tests/test_naive_rag_benchmark_v1.py; python3 -m py_compile eval/naive_rag/benchmark.py; python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py; python3 -m py_compile scripts/render_multi_chunk_evidence_failures.py rag_retrieval.py rag_core.py eval/naive_rag/benchmark.py; git diff --check; python3 -m pytest tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py -q -rA
- Results: all validation commands exited 0.
- Validation evidence: focused pytest, py_compile, and diff whitespace check passed locally.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: none committed.
- Blockers: none.
- Open risks: worktree contains unrelated/concurrent local edits outside this task; do not revert them. Benchmark Auditor noted broader contamination/provenance concerns in other files, but this checkpoint only claims multi-chunk profile observability.
- Next action: reviewer pass and decide issue/PR branch.
- Next safe command: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py
- Reviewer focus: additive-only output, no `run_rag_query` argument drift, closed bucket wording, public synthetic-only claim boundary.
```

```markdown
## Session Handoff - 2026-05-25 22:30 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: review
- Branch / worktree: dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Base branch: main
- Issue / PR: N/A / PR TBD
- Task: T-2026-0005
- Plan: docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Current status: integration review tightened the profile semantics and runner test after Adversarial Reviewer found the previous assertions were only shape checks.
- Files touched: eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py, docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md
- Decisions made: `not_observable` is separated from `top10_failure_count` as `top10_not_observable_count`; benchmark runner test now asserts the current public synthetic fixture bucket values.
- Commands run: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py; tmpdir=$(mktemp -d); python3 -m eval.naive_rag.benchmark --config configs/eval/benchmark_naive_rag_v1.yaml --run-id integration-profile-check --output-root "$tmpdir" ...; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py visual_ingestion.py parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py rag_indexing.py; git diff --check
- Results: all listed commands exited 0. Observed fixture profile: case_count=7, same_doc=7, all_gold_retrieved=6, partial_gold_retrieved=1, top10_failure_count=1, top10_not_observable_count=0.
- Validation evidence: focused pytest, direct benchmark profile check, py_compile, diff check.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: generated benchmark output under a mktemp directory only.
- Blockers: none for this checkpoint.
- Open risks: this is still observability for the current public synthetic fixture, not evidence of retrieval quality improvement.
- Next action: split this task into an issue-linked ADR 0007 branch before PR.
- Next safe command: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py
- Reviewer focus: actual bucket assertions, public synthetic-only wording, no retrieval/scoring behavior drift.
```
