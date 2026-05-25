# Persistent Task Queue

이 queue는 장기 AI-agent 작업의 operational state를 저장한다. 실제 GitHub issue와
PR이 생기면 각 task에 링크를 추가한다. 예제 task는 `tasks/examples/`에 있고,
아래 queue에는 현재 운영체계 도입 이후 실제로 수행할 수 있는 seed task만 둔다.

## T-2026-0001 — Benchmark hardening against synthetic contamination

- Status: backlog
- Owner role: Planner -> Benchmark Auditor -> Implementer
- Related issue: TBD
- Related PR: TBD
- Related plan: [`docs/plans/EXAMPLE-benchmark-hardening.md`](../docs/plans/EXAMPLE-benchmark-hardening.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

### Goal

Prevent public synthetic benchmark results from being inflated by leakage,
contaminated index inputs, or over-claiming.

### Context

- Surface: public synthetic benchmark.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [`docs/evaluation/synthetic_benchmark_v1_design.md`](../docs/evaluation/synthetic_benchmark_v1_design.md).
- Primary risk: synthetic-only success being read as real RFP performance.

### Scope

- Inspect benchmark validator and index builder input boundaries.
- Add focused tests or docs only if a concrete gap is found.
- Keep changes out of retrieval/answer production behavior.

### Non-Goals

- Do not improve benchmark score.
- Do not change private real-eval.
- Do not introduce a new benchmark dataset.

### Acceptance Criteria

- [ ] Benchmark index build is documented/tested as corpus-only.
- [ ] Benchmark claim wording is synthetic-only and links to the surface map.
- [ ] Benchmark Auditor checklist is satisfied.

### Validation Commands

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json

python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
```

### Evidence Required

- Validation report summary.
- Focused pytest output.
- Review note confirming no real-world performance claim.

### Failure Conditions

- Stop if index build reads questions/gold/expected answers.
- Stop if the task requires changing scoring semantics; that needs a new plan.

## T-2026-0002 — Eval regression safety surface separation

- Status: backlog
- Owner role: Planner -> Implementer -> Reviewer
- Related issue: TBD
- Related PR: TBD
- Related plan: TBD
- Created: 2026-05-25
- Last updated: 2026-05-25

### Goal

Make it harder for future agents to conflate public fixture smoke,
public synthetic benchmark, and private real-eval artifacts when reporting
regression evidence.

### Context

- Surface: eval governance.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md).
- Primary risk: comparing incompatible `eval_summary.json` files.

### Scope

- Add docs/tests only around artifact naming, provenance, or checklist gaps.
- Verify existing doc links and PR template wording.

### Non-Goals

- Do not change eval scoring.
- Do not run or expose private raw eval data.
- Do not make private real-eval a CI requirement.

### Acceptance Criteria

- [ ] Future agents can identify which `eval_summary.json` they are reading.
- [ ] Smoke/synthetic/private claims are explicitly separated.
- [ ] Reviewer checklist catches incompatible artifact comparisons.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all
python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q
```

### Evidence Required

- Doc link check output.
- Focused pytest output.
- Reviewer note confirming claim boundary clarity.

### Failure Conditions

- Stop if proposed changes require private raw artifact inspection.
- Stop if this expands into metric semantics; create a separate plan.
