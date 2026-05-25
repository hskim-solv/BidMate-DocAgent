# Plan: T-2026-0001 Benchmark Hardening Against Synthetic Contamination

- Status: proposed
- Owner role: Planner
- Related task: [`tasks/examples/benchmark-hardening.md`](../../tasks/examples/benchmark-hardening.md)
- Related issue / PR: example only
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

The public synthetic Naive RAG benchmark is useful for failure discovery, but it
can become misleading if the benchmark index reads question/gold/expected-answer
fields or if benchmark wording is used as real-world performance evidence.

## Current Behavior

Synthetic benchmark assets live under `data/eval/benchmark/` and
`configs/eval/benchmark_naive_rag_v1.yaml`. The design doc states that the index
must be built only from frozen corpus chunks and must not read questions, gold
evidence, expected answers, or expected terms. The claim boundary is documented,
but future agents can still weaken it by adding convenience code or docs that
blur smoke, synthetic benchmark, and private real-eval.

## Desired Behavior

Benchmark runs should remain useful for controlled synthetic failure discovery
without becoming evidence for real RFP performance. The benchmark validation path
should make contamination and over-claiming harder to miss.

## Constraints

- Scope constraints: add or verify benchmark validity checks and claim wording only.
- Architecture constraints: `naive_baseline` remains the control.
- Compatibility constraints: existing benchmark config and public synthetic data stay valid.
- Eval/privacy constraints: ADR 0005 privacy and public/private split remain unchanged.
- Tooling/CI constraints: generated run artifacts remain local unless explicitly allowed.
- Non-goals: do not improve retrieval, reranking, answer generation, verifier behavior,
  private real-eval scoring, or product-quality claims.

## Architecture Impact

- Affected modules or docs: `eval/naive_rag/validate_benchmark_dataset.py`,
  `eval/naive_rag/build_benchmark_index.py`, docs under `docs/evaluation/`.
- Affected contracts or invariants: synthetic benchmark v1 input separation and claim boundary.
- Load-bearing paths: `eval/` if validator or runner changes.
- ADR required: no unless a new measurement surface or claim contract is created.
- Backward compatibility expectation: existing benchmark corpus/config remains readable.

## Affected Interfaces

- CLI/API/config: benchmark validation and index build commands.
- Input data: `data/eval/benchmark/corpus_chunks_v1.jsonl` only for index build.
- Output artifacts: validation report under `reports/benchmark/`.
- Docs/review surfaces: benchmark design/results wording and Benchmark Auditor checklist.
- Tests/eval entrypoints: focused validator/index-build regression tests.

## Data / Eval Impact

- Surface: public synthetic benchmark.
- Data boundary: public synthetic corpus; generated run artifacts remain local.
- Allowed claim: benchmark hardening improved contamination resistance.
- Disallowed claim: RAG model quality improved on real RFPs.
- Baseline or control affected: no; `naive_baseline` remains the control.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Inspect benchmark index builder inputs and confirm it does not parse questions/gold.
2. Add regression coverage if the invariant is not already tested.
3. Tighten docs so synthetic result wording cannot be read as private real-eval evidence.
4. Run validation and focused tests.

## Acceptance Criteria

- [ ] Benchmark index builder reads `corpus_chunks_v1.jsonl` only.
- [ ] Validator catches missing/invalid explicit gold evidence and leakage warnings remain visible.
- [ ] Docs state that synthetic benchmark supports failure discovery, not real-world claims.
- [ ] Review checklist identifies benchmark auditor as required.

## Validation Strategy

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json

python3 -m eval.naive_rag.build_benchmark_index \
  --corpus data/eval/benchmark/corpus_chunks_v1.jsonl \
  --output data/eval/benchmark/index_v1

python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
python3 scripts/check_doc_links.py --check-all
```

Expected evidence:

- validation report path and summary counts.
- focused pytest result.
- no real-world performance claim in changed docs.

## Rollback Strategy

Revert validator/test/doc changes. Do not delete benchmark data unless the plan
explicitly changes dataset versioning.

## Failure Modes

- Index builder accidentally reads gold labels and inflates retrieval metrics.
- Docs imply synthetic benchmark performance generalizes to private RFPs.
- Validation report is generated but not reviewed.
- New tests assert implementation details instead of contamination boundary.

## Observability

- Validation report: leakage warnings, dataset counts, gold evidence summary.
- Test result: benchmark input separation and schema checks.
- Review output: Benchmark Auditor verdict.

## Reviewer Notes

Attack the claim wording first. Then inspect whether any code path can read
questions, expected answers, expected terms, or gold evidence during index build.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-25 00:00 KST

- Role: Planner
- Branch / worktree: example only
- Issue / PR: example only
- Task: T-EXAMPLE-001
- Current status: proposed example plan
- Files touched: N/A
- Decisions made: Treat this as benchmark validity hardening, not model improvement.
- Commands run: None; example only.
- Results: N/A
- Next safe command: python3 eval/naive_rag/validate_benchmark_dataset.py --help
- Open questions: whether a concrete validator gap exists.
- Risks: unsupported real-world claim wording or benchmark leakage.
```
