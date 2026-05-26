# Plan: T-2026-0004 Visual Ingestion Page Metadata Contract Guard

- Status: review
- Owner role: Planner + Implementer
- Related task: `tasks/queue.md::T-2026-0004`
- Related issue / PR: #1486 / #1490
- Related ADR: N/A - no decision-level change
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

Page metadata recovery is no longer blocked by chunk/index serialization alone:
visual parser output can already carry `sections[].page_span` and
`sections[].regions[].page_number`. The remaining first implementation risk is
that malformed parser output could enter ingestion and be normalized later,
turning a parser bug into silent page metadata drift.

## Current Behavior

- `parser_page_metadata_contract.py` validates parser sections and raises
  `PageMetadataContractError` for malformed page metadata.
- `visual_ingestion.py` builds visual sections with `page_span` and `regions`,
  then converts the artifact into the existing document shape.
- `rag_indexing.py` already preserves valid optional `regions` and `page_span`
  from sections to chunks.
- CSV/kordoc ingestion is intentionally page-blind and must not infer pages
  from plain text offsets.

## Desired Behavior

Visual parser output is checked against the existing page metadata contract
before it becomes a RAG document. Missing page metadata remains valid and
counts as uncovered, but malformed `page_span` or `regions.page_number`
fails loudly with aggregate-only error details.

## Constraints

- Scope constraints: limit implementation to visual parser output validation,
  focused tests, and handoff docs.
- Architecture constraints: reuse `parser_page_metadata_contract.py`; do not
  add a parallel page metadata schema.
- Compatibility constraints: keep page-blind CSV/kordoc and HWP visual fallback
  valid when page metadata is missing.
- Eval/privacy constraints: no private raw data, filenames, paths, `doc_id`,
  `chunk_id`, or raw text in reports/errors.
- Tooling/CI constraints: use focused pytest, `py_compile`, and `git diff --check`.
- Non-goals: no retrieval, verifier, prompt, answer generation, citation
  selection, ranking, full re-index, parser rewrite, or performance claim.

## Architecture Impact

- Affected modules or docs: `visual_ingestion.py`, `tests/test_visual_ingestion.py`,
  this plan.
- Affected contracts or invariants: additive enforcement of the existing
  page-aware parser output contract for visual ingestion output.
- Load-bearing paths: `visual_ingestion.py`.
- ADR required: no; this wires an accepted contract into one parser boundary
  without changing baseline, retrieval, answer schema, eval split, or privacy
  policy.
- Backward compatibility expectation: valid visual output and missing metadata
  continue to work; malformed page metadata now fails before document conversion.

## Affected Interfaces

- CLI/API/config: none.
- Input data: no new data requirement.
- Output artifacts: no new committed artifacts.
- Docs/review surfaces: task queue and plan handoff only.
- Tests/eval entrypoints: focused visual ingestion and parser contract tests.

## Data / Eval Impact

- Surface: docs/evaluation contract surface; no benchmark metric or private
  real-eval claim.
- Data boundary: synthetic unit fixtures only; no private raw data touched.
- Allowed claim: visual ingestion now has a regression guard for malformed page
  metadata at the parser output boundary.
- Disallowed claim: no RAG quality, citation precision, recall, or real-world
  performance improvement claim.
- Baseline or control affected: no.
- Benchmark/eval auditor required: yes, only for claim boundary review because
  this touches `docs/evaluation`-related page metadata surface.

## Task Breakdown

1. Add task queue entry and executable plan.
2. Add a visual ingestion contract guard using
   `validate_page_metadata_sections()`.
3. Add focused regression coverage for malformed visual parser sections and
   privacy-safe error/report content.
4. Run focused validation.
5. Update Session Handoff with files changed, commands, results, risks, and
   next safe command.

## Acceptance Criteria

- [x] Visual parser output with malformed `page_span` or
  `regions.page_number` raises `PageMetadataContractError` before document
  conversion.
- [x] Error message and report remain aggregate-only and do not include raw
  text, private paths, filenames, `doc_id`, `chunk_id`, or block IDs.
- [x] HWP visual fallback and missing page metadata remain accepted.
- [x] Existing page-aware parser contract tests still pass.
- [x] No retrieval, verifier, prompt, answer, citation selection, ranking, or
  eval metric behavior is changed.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py
python3 -m py_compile parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py visual_ingestion.py rag_indexing.py
git diff --check
```

Expected evidence:

- Test/eval output: focused pytest pass/fail output.
- Generated or updated artifact: none.
- Reviewer checklist or manual inspection: Normal Code Review, Adversarial
  Review, Benchmark Validity Audit claim-boundary check.
- Explicitly not validated, with reason: private real-eval not run; this change
  makes no private real-data or performance claim.

## Rollback Strategy

Revert the `visual_ingestion.py` guard and focused test. Do not delete or
modify existing page metadata contract fixtures or private/local eval artifacts.

## Failure Modes

- Failure mode: guard includes unsafe source labels.
  Detection signal: privacy assertions fail or report contains filenames/paths.
  Stop condition or fallback: use a fixed aggregate source group label only.
- Failure mode: missing page metadata starts failing.
  Detection signal: HWP fallback or parser contract missing-metadata tests fail.
  Stop condition or fallback: validate with the existing contract semantics,
  where missing metadata is uncovered but valid.
- Failure mode: runtime normalizers are changed instead of parser boundary.
  Detection signal: broad test failures or diff touches retrieval/answer paths.
  Stop condition or fallback: move validation back to visual ingestion boundary.

## Observability

- Focused pytest result for visual ingestion and parser contract tests.
- `py_compile` result for parser/audit/ingestion/indexing files.
- `git diff --check` result.

## Reviewer Notes

Attack privacy and silent behavior changes first: malformed visual page metadata
must fail before document conversion, but missing metadata must remain valid.
Also verify no search ranking, answer, verifier, prompt, citation selection, or
metric semantics changed.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-25 23:25 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: draft PR preparation
- Branch / worktree: fix/issue-1486-visual-page-metadata-contract / /Users/hskim/.codex/worktrees/1486/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1486 / #1490
- Task: T-2026-0004
- Plan: docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md
- Current status: split from the mixed integration worktree onto an issue-linked ADR 0007 branch; focused validation passed and draft PR #1490 is open.
- Files touched: docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md, visual_ingestion.py, tests/test_visual_ingestion.py
- Decisions made: keep the first executable checkpoint at the visual parser output boundary; malformed `page_span` or `regions.page_number` fails loudly via the existing page metadata contract; missing page metadata remains valid.
- Commands run: git worktree add -b fix/issue-1486-visual-page-metadata-contract /Users/hskim/.codex/worktrees/1486/BidMate-DocAgent origin/main; git diff -- visual_ingestion.py tests/test_visual_ingestion.py | git -C /Users/hskim/.codex/worktrees/1486/BidMate-DocAgent apply; git diff --no-index ... plan copy via mktemp + git apply; python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py; python3 -m py_compile parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py visual_ingestion.py rag_indexing.py; python3 scripts/check_doc_links.py --check-all; git diff --check.
- Results: branch split completed; all listed validation commands exited 0; draft PR #1490 opened.
- Validation evidence: focused pytest passed; py_compile passed; doc link check reported no broken links; diff check passed.
- Eval surface: page-aware parser contract / ingestion guard; no benchmark metric or private real-eval claim.
- Evidence artifacts: none.
- Blockers: none.
- Open risks: malformed visual page metadata now raises before normal failed-artifact conversion; PR reviewer should confirm this fail-loud behavior is acceptable.
- Next action: review draft PR #1490 and confirm the fail-loud visual parser boundary behavior.
- Next safe command: python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py
- Reviewer focus: privacy-safe exception/report content, missing metadata acceptance, no retrieval/ranking/answer/citation/metric behavior change.

## Session Handoff - 2026-05-25 19:48 KST

- Role: Planner + Implementer
- Branch / worktree: dev/multi-chunk-evidence-first-step (observed at handoff; initial local checkpoint branch was dev/page-metadata-recovery-first-step) / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Issue / PR: N/A / PR TBD
- Task: T-2026-0004
- Current status: review; implementation and focused validation complete.
- Files touched: docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md, tasks/queue.md, visual_ingestion.py, tests/test_visual_ingestion.py
- Decisions made: first executable checkpoint is visual parser output contract guard, not full re-index or retrieval behavior; use a fixed aggregate source group label for privacy; preserve non-list `sections` values so the contract can fail loudly instead of coercing them to empty.
- Commands run: date '+%Y-%m-%d %H:%M %Z'; python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py; python3 -m py_compile parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py visual_ingestion.py rag_indexing.py; git diff --check; adversarial reviewer pass via subagent, then focused pytest/py_compile/git diff --check rerun.
- Results: validation commands exited 0 before and after adversarial-review fixes.
- Next safe command: python3 -m pytest -q tests/test_visual_ingestion.py tests/test_page_aware_parser_contract.py
- Open questions: PR branch must be renamed to an issue-linked ADR 0007 branch before opening a PR.
- Risks: load-bearing ingestion path touched; PR must include §5b real-data delta or no-behavior-change attestation. Worktree also contains unrelated/concurrent dirty files outside this task, and current branch is not the initial page-metadata branch.
```

```markdown
## Session Handoff - 2026-05-25 22:30 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: review
- Branch / worktree: dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Base branch: main
- Issue / PR: N/A / PR TBD
- Task: T-2026-0004
- Plan: docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md
- Current status: integration review found no code conflict with other workstreams; validation rerun passed.
- Files touched: docs/plans/T-2026-0004-visual-ingestion-page-metadata-contract-guard.md
- Decisions made: keep behavior as fail-loud at visual parser output boundary; PR text must call out that malformed page metadata now raises before normal failed-artifact handling.
- Commands run: python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py visual_ingestion.py parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py rag_indexing.py; git diff --check
- Results: all listed commands exited 0.
- Validation evidence: focused visual/parser pytest, py_compile, diff check.
- Eval surface: page-aware parser contract / ingestion guard; no benchmark metric or private real-eval claim.
- Evidence artifacts: none.
- Blockers: none for this checkpoint.
- Open risks: batch metadata CSV error propagation is not separately tested; reviewer should decide whether that is required before PR.
- Next action: split this task into an issue-linked ADR 0007 branch before PR.
- Next safe command: python3 -m pytest -q tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_visual_ingestion.py tests/test_ingestion_kordoc_regression.py
- Reviewer focus: privacy-safe exception/report, missing page metadata remains valid, explicit fail-loud behavior in PR description.
```
