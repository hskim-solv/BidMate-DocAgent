# Persistent Task Queue

이 queue는 장기 AI-agent 작업의 operational state를 저장한다. 실제 GitHub issue와
PR이 생기면 각 task에 링크를 추가한다. 예제 task는 `tasks/examples/`에 있고,
아래 queue에는 현재 운영체계 도입 이후 실제로 수행할 수 있는 seed task만 둔다.

## Ready Order

새 세션은 이 표에서 위에서부터 첫 `ready` task를 선택한다. `backlog`는 ready
조건이 부족한 작업이고, `review`는 구현보다 검토가 우선이다.

| Order | ID | Status | Owner role | Why ready / not ready |
|---:|---|---|---|---|
| 1 | `T-2026-0001` | `review` | Implementer -> Benchmark Auditor -> Reviewer | corpus-only benchmark index boundary report와 focused tests 추가됨. |
| 2 | `T-2026-0002` | `review` | Implementer -> Reviewer | eval summary surface label + opt-in mismatch gate와 focused tests 추가됨. |

## Examples

- [`tasks/examples/benchmark-hardening.md`](examples/benchmark-hardening.md): benchmark hardening task 작성 예시.
- [`tasks/examples/eval-regression-safety.md`](examples/eval-regression-safety.md): eval regression safety task 작성 예시.

## T-2026-0001 — Benchmark hardening against synthetic contamination

- ID: T-2026-0001
- Title: Benchmark hardening against synthetic contamination
- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
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

- [x] Benchmark index build is documented/tested as corpus-only.
- [x] Benchmark claim wording is synthetic-only and links to the surface map.
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

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0001-benchmark-contamination-guard.md`](../docs/plans/T-2026-0001-benchmark-contamination-guard.md)
- Issue: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480)
- PR: TBD
- ADR: [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)
- Report: TBD

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 00:00 KST

- Role: Task Queue Designer
- Branch / worktree: TBD by implementer
- Current status: ready
- Decisions made: Treat this as benchmark validity hardening, not metric improvement.
- Commands run: None yet.
- Results: Task is ready when an implementer can run validation commands or document why a command is unavailable.
- Next safe command: inspect benchmark validator and index build inputs.
- Risks: Scope creep into scoring semantics or unsupported real-eval claims.
```

```markdown
## Session Handoff — 2026-05-25 18:49 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0001
- Plan: docs/plans/T-2026-0001-benchmark-contamination-guard.md
- Current status: corpus-only index boundary report and regression tests added.
- Files touched: eval/naive_rag/validate_benchmark_dataset.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: Additive validator report only; no benchmark scoring or retrieval behavior change.
- Commands run: python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json; python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass; validation report index_build_boundary.status=pass.
- Validation evidence: reports/benchmark/naive_rag_v1_validation.json generated locally.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: local validation JSON only.
- Open risks: Benchmark Auditor still needs to confirm no real-world performance claim is implied.
- Next action: Review diff and benchmark validity checklist.
- Next safe command: python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
- Reviewer focus: corpus-only proof, prohibited label fields, no metric semantics change.
```

## T-2026-0002 — Eval regression safety surface separation

- ID: T-2026-0002
- Title: Eval regression safety surface separation
- Status: review
- Owner role: Implementer -> Reviewer
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

- [x] Future agents can identify which `eval_summary.json` they are reading.
- [x] Smoke/synthetic/private claims are explicitly separated.
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

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0002-eval-artifact-surface-guard.md`](../docs/plans/T-2026-0002-eval-artifact-surface-guard.md)
- Issue: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480)
- PR: TBD
- ADR: [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)
- Report: TBD

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 00:00 KST

- Role: Task Queue Designer
- Branch / worktree: TBD by implementer
- Current status: ready
- Decisions made: Treat smoke, synthetic benchmark, and private real-eval as separate evidence surfaces.
- Commands run: None yet.
- Results: Task is ready when an implementer can prove artifact provenance or document manual validation.
- Next safe command: inspect eval artifact docs and existing regression tests.
- Risks: Accidentally requiring private raw data or comparing incompatible summaries.
```

```markdown
## Session Handoff — 2026-05-25 18:49 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0002
- Plan: docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Current status: compare_eval surface labels and opt-in surface mismatch gate added.
- Files touched: scripts/compare_eval.py, tests/test_compare_eval_regression_gate.py
- Decisions made: Unknown surfaces remain visible but non-blocking by default to preserve PR eval compatibility.
- Commands run: python3 -m pytest tests/test_compare_eval_regression_gate.py -q; python3 scripts/check_doc_links.py --check-all; python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass.
- Validation evidence: focused tests and doc link check.
- Eval surface: eval governance; no benchmark metric semantics changed.
- Evidence artifacts: none committed.
- Open risks: Reviewer should decide whether CI should enable --fail-on-surface-mismatch later.
- Next action: Review diff and normal/governance checklist.
- Next safe command: python3 -m pytest tests/test_compare_eval_regression_gate.py -q
- Reviewer focus: backward-compatible output shape, no private raw data dependency, no incompatible surface overclaim.
```
