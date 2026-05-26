# Plan: T-2026-0001 Benchmark Integrity Follow-up

- Status: review
- Owner role: Implementer
- Related task: `tasks/queue.md::T-2026-0001`
- Related issue / PR: [#1485](https://github.com/hskim-solv/BidMate-DocAgent/issues/1485) / PR TBD
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

T-2026-0001 already added corpus-only index boundary checks. The remaining risk
inside the same benchmark-integrity surface is that a future benchmark config can
look syntactically valid while missing claim-boundary metadata or accidentally
pointing benchmark paths at public smoke fixture assets.

## Current Behavior

`eval/naive_rag/validate_benchmark_dataset.py` validates benchmark type,
version, `not_ci_smoke`, corpus/gold evidence consistency, leakage heuristics,
and corpus-only index build boundaries. It does not yet make required
`dataset_metadata` fields a validator contract, and it does not explicitly fail
when benchmark paths point at smoke fixture paths such as `data/index` or
`data/eval/rag_questions.jsonl`.

## Desired Behavior

The benchmark validator fails with clear errors when:

- required public synthetic benchmark metadata is missing or misclassified.
- benchmark corpus/index/question/gold paths reuse public fixture smoke assets.
- index build output configuration drifts away from benchmark `index_dir`.

The benchmark runner also refuses a stale or contaminated `index.json` whose
recorded corpus provenance does not match the configured benchmark corpus.

## Constraints

- Scope constraints: only benchmark integrity validation and focused tests.
- Architecture constraints: no retrieval, scoring, or answer-generation changes.
- Compatibility constraints: additive validation/report fields only.
- Eval/privacy constraints: public synthetic benchmark only; no private data.
- Tooling/CI constraints: focused pytest and py_compile should cover the change.
- Non-goals: no benchmark score improvement, no metric semantics change, no new dataset.

## Architecture Impact

- Affected modules or docs: `eval/naive_rag/validate_benchmark_dataset.py`,
  `eval/naive_rag/benchmark.py`, `tests/test_naive_rag_benchmark_v1.py`,
  this plan, and task handoff.
- Affected contracts or invariants: benchmark config validity only.
- Load-bearing paths: `eval/`.
- ADR required: no, this hardens an existing surface without changing its meaning.
- Backward compatibility expectation: existing valid v1 config remains valid.

## Affected Interfaces

- CLI/API/config: `validate_benchmark_dataset.py --config ...` may now reject
  incomplete or smoke-contaminated benchmark configs.
- Input data: no dataset content changes.
- Output artifacts: validation JSON gains benchmark metadata/path boundary blocks.
- Docs/review surfaces: Benchmark Validity Audit gets machine-readable evidence.
- Tests/eval entrypoints: focused benchmark tests.

## Data / Eval Impact

- Surface: public synthetic benchmark.
- Data boundary: public synthetic benchmark config and fixture paths only.
- Allowed claim: validator hardens synthetic benchmark contamination checks.
- Disallowed claim: any real-world RFP performance claim.
- Baseline or control affected: no, benchmark retrieval and metrics are unchanged.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Add validator checks for required `dataset_metadata` and public synthetic surface classification.
2. Add validator checks that benchmark paths do not reuse public fixture smoke paths.
3. Add validator checks that `index_build.output_dir` and command `--output` match `index_dir`.
4. Add runner checks for loaded index provenance before benchmark execution.
5. Add focused regression tests for missing metadata, smoke path contamination, output drift, and stale index provenance.
6. Run focused validation and record handoff evidence.

## Acceptance Criteria

- [x] Valid benchmark config still passes validation.
- [x] Validator fails when `dataset_metadata.privacy` or claim-boundary fields are missing or wrong.
- [x] Validator fails when benchmark paths point at smoke fixture assets.
- [x] Validator fails when `index_build.output_dir` or command `--output` drifts away from `index_dir`.
- [x] Benchmark runner fails before query execution when `index.json` provenance does not match `corpus_path`.
- [x] Benchmark runner fails when `index.json` chunk ids/order/metadata/text are stale relative to `corpus_path`.
- [x] Validator normalizes smoke fixture paths and rejects smoke paths embedded in `index_build.command`.
- [x] Focused pytest and py_compile pass.

## Validation Strategy

Commands that must be run:

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json
python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py
git diff --check
```

Expected evidence:

- Test/eval output: validator pass and focused pytest pass.
- Generated or updated artifact: local validation JSON under `reports/benchmark/`.
- Reviewer checklist or manual inspection: Benchmark Validity Audit.
- Explicitly not validated, with reason: private real-eval is out of scope.

## Rollback Strategy

Revert validator and focused test changes. Do not delete benchmark dataset files
or generated local reports unless they were created by this session and remain
untracked.

## Failure Modes

- Failure mode: guard rejects the existing valid benchmark config.
- Detection signal: validator CLI or focused pytest fails.
- Stop condition or fallback: fix only if failure is in the new guard; otherwise
  stop and record the blocker.

## Observability

- `reports/benchmark/naive_rag_v1_validation.json` exposes metadata/path/output boundary checks.
- `tests/test_naive_rag_benchmark_v1.py` covers valid and contaminated configs.

## Reviewer Notes

Attack claim-boundary drift first: the validator should not allow a benchmark
config that is missing synthetic-only metadata or that reuses smoke fixture
paths.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-25 19:45 KST

- Role: Implementer
- Branch / worktree: started on fix/issue-1480-benchmark-integrity-followup; current branch observed as dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Issue / PR: #1485 / PR TBD
- Task: T-2026-0001 benchmark integrity follow-up
- Current status: implementation complete; local validation passed; ready for review.
- Files touched: docs/plans/T-2026-0001-benchmark-integrity-followup.md, eval/naive_rag/validate_benchmark_dataset.py, eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: keep this as additive benchmark integrity validation; do not change retrieval, scoring, or answer semantics.
- Commands run: python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json; python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q; python3 -m pytest tests/test_naive_rag_benchmark_v1.py tests/test_synthetic_benchmark_dataset.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py; git diff --check; git diff --check -- docs/plans/T-2026-0001-benchmark-integrity-followup.md eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/benchmark.py tests/test_naive_rag_benchmark_v1.py
- Results: pass. Validation report shows benchmark_metadata.status=pass, smoke_fixture_path_boundary.status=pass, index_build_boundary.status=pass, command_writes_index_dir=True. Adversarial reviewer findings on stale index content and path/command smoke bypass were addressed with focused tests. Benchmark auditor also flagged unrelated `multi_chunk_evidence_profile` metric surface in the current worktree diff; it remains outside this follow-up scope and should not be included in a benchmark-integrity-only PR.
- Next safe command: python3 -m pytest tests/test_naive_rag_benchmark_v1.py tests/test_synthetic_benchmark_dataset.py -q
- Open questions: none for this checkpoint.
- Risks: worktree contains unrelated local changes in tasks/queue.md, scripts/compare_eval.py, visual_ingestion.py, related tests, docs/plans/T-2026-0002-eval-artifact-surface-guard.md, docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md, and docs/plans/T-2026-0005-multi-chunk-evidence-regression-guard.md. `eval/naive_rag/benchmark.py` and `tests/test_naive_rag_benchmark_v1.py` also contain unrelated `multi_chunk_evidence_profile` metric changes; keep review/commit scope limited to the integrity guard lines or split that metric work into its own task/plan.
```

```markdown
## Session Handoff - 2026-05-25 22:30 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: review
- Branch / worktree: fix/issue-1485-benchmark-integrity-followup / /Users/hskim/.codex/worktrees/1485/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1485 / PR TBD
- Task: T-2026-0001 benchmark integrity follow-up
- Plan: docs/plans/T-2026-0001-benchmark-integrity-followup.md
- Current status: integration review tightened benchmark index provenance comparison after Benchmark Auditor found metadata drift could pass.
- Files touched: eval/naive_rag/benchmark.py, tests/test_naive_rag_benchmark_v1.py, docs/plans/T-2026-0001-benchmark-integrity-followup.md
- Decisions made: compare full corpus/index chunk dicts while excluding volatile `embedding` and `embedding_idx`; keep this as validation-only with no retrieval/scoring behavior change.
- Commands run: python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json; python3 -m pytest -q tests/test_naive_rag_benchmark_v1.py tests/test_synthetic_benchmark_dataset.py; python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_naive_rag_benchmark_v1.py; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py visual_ingestion.py parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py rag_indexing.py; git diff --check
- Results: all listed commands exited 0; validator report status remained pass with the existing lexical leakage warning.
- Validation evidence: focused pytest, validator CLI, py_compile, diff check.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: local reports/benchmark/naive_rag_v1_validation.json only.
- Blockers: none for this checkpoint.
- Open risks: stale embedding sidecar with identical chunk metadata is not recomputed in this guard; do not claim full contamination proof beyond corpus/index metadata boundary.
- Next action: review and publish draft PR for issue #1485.
- Next safe command: python3 -m pytest -q tests/test_naive_rag_benchmark_v1.py tests/test_synthetic_benchmark_dataset.py
- Reviewer focus: full chunk provenance comparison, no metric semantics change, public synthetic-only claim wording.
```
