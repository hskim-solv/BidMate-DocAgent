# Plan: T-2026-0001 Benchmark Hardening Against Synthetic Contamination

- Status: example
- Owner role: Planner
- Related task: [`tasks/examples/benchmark-hardening.md`](../../tasks/examples/benchmark-hardening.md)
- Related issue / PR: example only
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

## Scope

- Add or verify checks that benchmark index build reads only corpus chunks.
- Add reviewer-facing documentation that benchmark claims are synthetic-only.
- Add regression tests for validator behavior if code changes are needed.

## Non-Goals

- Do not improve retrieval, reranking, answer generation, or verifier behavior.
- Do not change private real-eval scoring.
- Do not add a new benchmark dataset.
- Do not claim product-quality improvement.

## Constraints

- ADR 0005 privacy and public/private split remain unchanged.
- `naive_baseline` remains the control.
- Public synthetic data may be committed; generated run artifacts remain local.
- Any claim-bearing doc must link to [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md).

## Architecture Impact

- Affected modules: `eval/naive_rag/validate_benchmark_dataset.py`,
  `eval/naive_rag/build_benchmark_index.py`, docs under `docs/evaluation/`.
- Affected contracts: synthetic benchmark v1 input separation and claim boundary.
- Load-bearing paths: `eval/` if validator or runner changes.
- ADR impact: no new ADR unless a new measurement surface or claim contract is created.

## Affected Interfaces

- CLI: benchmark validation and index build commands.
- Output artifacts: validation report under `reports/benchmark/`.
- Docs: benchmark design/results wording.
- Tests: focused validator/index-build regression tests.

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

## Eval / Benchmark Impact

- Surface: public synthetic benchmark.
- Allowed claim: benchmark hardening improved contamination resistance.
- Disallowed claim: RAG model quality improved on real RFPs.
- Benchmark auditor required: yes.

## Reviewer Notes

Attack the claim wording first. Then inspect whether any code path can read
questions, expected answers, expected terms, or gold evidence during index build.
