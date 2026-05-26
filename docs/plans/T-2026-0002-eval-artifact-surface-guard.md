# Plan: T-2026-0002 Eval Artifact Surface Guard

- Status: review
- Owner role: Implementer
- Related task: `tasks/queue.md::T-2026-0002`
- Related issue / PR: [#1487](https://github.com/hskim-solv/BidMate-DocAgent/issues/1487) / PR TBD
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

Multiple files named `eval_summary.json` exist across public fixture smoke,
public synthetic benchmark, private real-eval, and harness runs. The default
delta comparator did not identify the surface being compared, so incompatible
artifact comparisons could look legitimate.

## Desired Behavior

`scripts/compare_eval.py` renders best-effort surface labels for base/head
summaries and offers an opt-in fail-closed gate for mismatched known surfaces.
Unknown surfaces remain non-blocking but visible.

Follow-up 01B also renders privacy-safe run/config/index/dataset provenance
before the metric table. Missing provenance and comparable provenance mismatch
are warned by default and can fail closed with opt-in CLI flags.

## Constraints

- Do not change metric calculation or regression thresholds.
- Do not require private raw data or make private real-eval a CI dependency.
- Keep existing PR fixture smoke workflow backward compatible.

## Architecture Impact

- Affected modules: eval delta comparator and focused CLI tests.
- Load-bearing paths: none directly, but this is eval governance tooling.
- ADR required: no, this enforces existing ADR 0005 surface separation.
- Backward compatibility: default compare remains non-blocking for unknown or matching surfaces.

## Validation Strategy

```bash
python3 -m pytest tests/test_compare_eval_regression_gate.py -q
python3 -m pytest -q tests/test_compare_eval_regression_gate.py tests/test_run_real_eval_delta.py tests/test_eval_artifact_privacy_regression.py tests/test_render_difficulty_profile.py
python3 scripts/check_doc_links.py --check-all
python3 -m py_compile scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py
git diff --check
```

## Reviewer Notes

Attack claim boundary wording first: smoke, synthetic benchmark, private
real-eval, and harness summaries must not be silently treated as interchangeable.

## Session Handoff

```markdown
## Session Handoff — 2026-05-25 19:46 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: fix/issue-1487-eval-provenance-comparator / /Users/hskim/.codex/worktrees/1487/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1487 / PR TBD
- Task: T-2026-0002 follow-up 01B
- Plan: docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Current status: compare_eval provenance rendering and opt-in strict gates implemented; adversarial review blockers addressed and re-review approved; focused validation passed.
- Files touched: scripts/compare_eval.py, tests/test_compare_eval_regression_gate.py, docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Decisions made: default comparator remains backward-compatible; missing/mismatched provenance is warning-only unless `--fail-on-missing-provenance` or `--fail-on-provenance-mismatch` is passed.
- Commands run: python3 -m pytest tests/test_compare_eval_regression_gate.py -q; python3 -m py_compile scripts/compare_eval.py; python3 -m pytest -q tests/test_compare_eval_regression_gate.py tests/test_run_real_eval_delta.py tests/test_eval_artifact_privacy_regression.py tests/test_render_difficulty_profile.py; python3 -m py_compile scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py; python3 scripts/check_doc_links.py --check-all; git diff --check
- Results: all listed commands exited 0.
- Validation evidence: focused comparator regression suite plus private aggregate/privacy renderer suites.
- Eval surface: PR fixture eval / eval governance comparator guard; no scoring semantics or benchmark metric changed.
- Evidence artifacts: none.
- Blockers: none.
- Open risks: existing worktree has unrelated in-progress changes (`eval/naive_rag/*`, `visual_ingestion.py`, `tests/test_visual_ingestion.py`, `tests/test_naive_rag_benchmark_v1.py`, `tasks/queue.md`, and untracked plan docs); reviewer should isolate this follow-up diff when reviewing.
- Next action: review the isolated T-2026-0002 follow-up diff.
- Next safe command: python3 -m pytest -q tests/test_compare_eval_regression_gate.py tests/test_run_real_eval_delta.py tests/test_eval_artifact_privacy_regression.py tests/test_render_difficulty_profile.py
- Reviewer focus: provenance rendering is privacy-safe, strict flags are opt-in, metric/regression exit-code semantics unchanged.
```

```markdown
## Session Handoff — 2026-05-25 22:30 KST

- Role: Maintainer + Integration Reviewer
- Lifecycle stage: review
- Branch / worktree: dev/multi-chunk-evidence-first-step / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1480 / PR TBD
- Task: T-2026-0002 follow-up 01B
- Plan: docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Current status: integration review addressed provenance fake-progress risks from Benchmark Auditor and Adversarial Reviewer.
- Files touched: scripts/compare_eval.py, tests/test_compare_eval_regression_gate.py, docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Decisions made: dataset count-only summaries no longer satisfy required dataset provenance; path-based config/index/dataset provenance includes a short path hash with basename redaction to detect same-basename mismatches without printing raw private paths.
- Commands run: python3 -m pytest -q tests/test_compare_eval_regression_gate.py tests/test_run_real_eval_delta.py tests/test_eval_artifact_privacy_regression.py tests/test_render_difficulty_profile.py; python3 scripts/check_doc_links.py --check-all; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py eval/naive_rag/build_benchmark_index.py eval/naive_rag/benchmark.py scripts/compare_eval.py scripts/run_real_eval_delta.py scripts/render_difficulty_profile.py visual_ingestion.py parser_page_metadata_contract.py scripts/page_metadata_recovery_audit.py ingestion.py rag_indexing.py; git diff --check
- Results: all listed commands exited 0.
- Validation evidence: focused comparator/privacy tests, doc link check, py_compile, diff check.
- Eval surface: PR fixture eval / eval governance comparator guard.
- Evidence artifacts: none.
- Blockers: none for this checkpoint.
- Open risks: comparator still cannot prove file content equality when only paths are available; exact comparability requires explicit sha/fingerprint fields.
- Next action: review and publish draft PR for issue #1487.
- Next safe command: python3 -m pytest -q tests/test_compare_eval_regression_gate.py tests/test_run_real_eval_delta.py tests/test_eval_artifact_privacy_regression.py tests/test_render_difficulty_profile.py
- Reviewer focus: privacy-safe provenance rendering, fail-closed flags remain opt-in, no metric threshold/exit-code drift.
```
