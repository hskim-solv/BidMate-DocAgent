# T-EXAMPLE-001 — Benchmark hardening against synthetic contamination

- ID: T-EXAMPLE-001
- Title: Benchmark hardening against synthetic contamination
- Status: ready
- Owner role: Benchmark Auditor
- Created: 2026-05-25
- Last updated: 2026-05-25

## Goal

Ensure the public synthetic benchmark cannot accidentally use question/gold data
during index build and cannot be reported as private real-eval performance.

## Context

Synthetic benchmark assets live under `data/eval/benchmark/` and are documented
in [`docs/evaluation/synthetic_benchmark_v1_design.md`](../../docs/evaluation/synthetic_benchmark_v1_design.md).
The benchmark is useful for failure discovery, not real RFP quality claims.

## Scope

- Inspect benchmark dataset validation and index build input boundaries.
- Add focused regression coverage if the boundary is not already enforced.
- Tighten claim wording in docs if needed.

## Non-Goals

- No retrieval or answer quality improvements.
- No private real-eval changes.
- No new benchmark corpus.

## Acceptance Criteria

- [ ] Index build reads corpus chunks only.
- [ ] Gold evidence remains explicit and not derived from `expected_terms`.
- [ ] Docs state synthetic-only claim boundary.
- [ ] Benchmark Auditor signs off.

## Validation Commands

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json
python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
```

## Evidence Required

- Validation report summary.
- Focused pytest result.
- Checklist result from [`docs/reviews/ai-review-checklists.md`](../../docs/reviews/ai-review-checklists.md).

## Failure Conditions

- Stop if benchmark scoring semantics need to change.
- Stop if the task starts optimizing model quality instead of hardening validity.

## Related Plan / Issue / PR Links

- Plan: [`docs/plans/EXAMPLE-benchmark-hardening.md`](../../docs/plans/EXAMPLE-benchmark-hardening.md)
- Issue: example only
- PR: example only
- ADR: [ADR 0005](../../docs/adr/0005-eval-split-public-synthetic-private-local.md)
- Report: example only

## Handoff Notes

```markdown
## Session Handoff — 2026-05-25 00:00 KST

- Role: Benchmark Auditor
- Branch / worktree: example only
- Current status: ready
- Decisions made: Separate synthetic benchmark claims from private real-eval claims.
- Commands run: None; example task.
- Results: N/A.
- Next safe command: inspect benchmark dataset validator and index build inputs.
- Risks: Metric inflation, benchmark leakage, or unsupported real-world quality claims.
```
