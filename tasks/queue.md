# Persistent Task Queue

이 queue는 장기 AI-agent 작업의 operational state를 저장한다. 실제 GitHub issue와
PR이 생기면 각 task에 링크를 추가한다. 예제 task는 `tasks/examples/`에 있고,
아래 queue에는 현재 운영체계 도입 이후 실제로 수행할 수 있는 seed task만 둔다.

## Ready Order

새 세션은 이 표에서 위에서부터 첫 `ready` task를 선택한다. `backlog`는 ready
조건이 부족한 작업이고, `review`는 구현보다 검토가 우선이다.

| Order | ID | Status | Owner role | Why ready / not ready |
|---:|---|---|---|---|
| 1 | `T-2026-0001` | `done` | Implementer -> Benchmark Auditor -> Reviewer | merged in PR #1481. |
| 2 | `T-2026-0002` | `done` | Implementer -> Reviewer | merged in PR #1481. |
| 3 | `T-2026-0003` | `review` | Implementer -> Reviewer | auto-ship Stage 5 Desktop main fast-forward sync 구현됨. |
| 4 | `T-2026-0004` | `review` | Implementer -> Reviewer | HWP -> PDF -> PyMuPDF4LLM opt-in loader 구현됨. |

## Examples

- [`tasks/examples/benchmark-hardening.md`](examples/benchmark-hardening.md): benchmark hardening task 작성 예시.
- [`tasks/examples/eval-regression-safety.md`](examples/eval-regression-safety.md): eval regression safety task 작성 예시.

## T-2026-0001 — Benchmark hardening against synthetic contamination

- ID: T-2026-0001
- Title: Benchmark hardening against synthetic contamination
- Status: done
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
- [x] Benchmark Auditor checklist is satisfied.

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
- PR: [#1481](https://github.com/hskim-solv/BidMate-DocAgent/pull/1481)
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
- Lifecycle stage: done
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0001
- Plan: docs/plans/T-2026-0001-benchmark-contamination-guard.md
- Current status: merged in PR #1481.
- Files touched: eval/naive_rag/validate_benchmark_dataset.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: Additive validator report only; no benchmark scoring or retrieval behavior change.
- Commands run: python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json; python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass; validation report index_build_boundary.status=pass; PR #1481 merged.
- Validation evidence: reports/benchmark/naive_rag_v1_validation.json generated locally.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: local validation JSON only.
- Open risks: none for this task; follow-up benchmark expansion remains separate.
- Next action: N/A
- Next safe command: N/A
- Reviewer focus: corpus-only proof, prohibited label fields, no metric semantics change.
```

## T-2026-0002 — Eval regression safety surface separation

- ID: T-2026-0002
- Title: Eval regression safety surface separation
- Status: done
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
- [x] Reviewer checklist catches incompatible artifact comparisons.

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
- PR: [#1481](https://github.com/hskim-solv/BidMate-DocAgent/pull/1481)
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
- Lifecycle stage: done
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0002
- Plan: docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Current status: merged in PR #1481.
- Files touched: scripts/compare_eval.py, tests/test_compare_eval_regression_gate.py
- Decisions made: Unknown surfaces remain visible but non-blocking by default to preserve PR eval compatibility.
- Commands run: python3 -m pytest tests/test_compare_eval_regression_gate.py -q; python3 scripts/check_doc_links.py --check-all; python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass; PR #1481 merged.
- Validation evidence: focused tests, doc link check, PR Eval Delta.
- Eval surface: eval governance; no benchmark metric semantics changed.
- Evidence artifacts: none committed.
- Open risks: Reviewer should decide whether CI should enable --fail-on-surface-mismatch later.
- Next action: no action; follow-up CI wiring would be a separate task.
- Next safe command: N/A
- Reviewer focus: backward-compatible output shape, no private raw data dependency, no incompatible surface overclaim.
```

## T-2026-0003 — Desktop main auto-sync after auto-ship merge

- ID: T-2026-0003
- Title: Desktop main auto-sync after auto-ship merge
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-25
- Last updated: 2026-05-25

### Goal

After a successful auto-ship merge, make the canonical Desktop checkout's
`main` match GitHub `origin/main` without requiring a manual pull.

### Context

- Surface: developer tooling / auto-ship.
- Relevant docs: [`docs/operations/auto-ship.md`](../docs/operations/auto-ship.md).
- Primary risk: stale Desktop `main` causing follow-up work to branch from an old base.

### Scope

- Add a fail-soft sync helper.
- Call it from auto-ship Stage 5 after merge success.
- Add focused temp-repo tests.

### Non-Goals

- Do not reset or discard local Desktop work.
- Do not make Desktop sync a merge blocker.
- Do not alter eval/runtime behavior.

### Acceptance Criteria

- [x] Clean Desktop `main` fast-forwards to `origin/main`.
- [x] Dirty or divergent Desktop `main` is skipped.
- [x] Auto-ship Stage 5 invokes the helper after merge success.

### Validation Commands

```bash
python3 -m pytest tests/test_sync_desktop_main.py -q
python3 -m py_compile scripts/sync_desktop_main.py
git diff --check
```

### Evidence Required

- Focused pytest output.
- Manual note that Desktop main was synced after #1481 merge.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0003-desktop-main-auto-sync.md`](../docs/plans/T-2026-0003-desktop-main-auto-sync.md)
- Issue: [#1482](https://github.com/hskim-solv/BidMate-DocAgent/issues/1482)
- PR: TBD
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 19:20 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1482-desktop-main-sync / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0003
- Plan: docs/plans/T-2026-0003-desktop-main-auto-sync.md
- Current status: fail-soft sync helper and Stage 5 hook added.
- Files touched: scripts/sync_desktop_main.py, scripts/claude-hooks/stop-ship.sh, tests/test_sync_desktop_main.py, docs/operations/auto-ship.md, tasks/queue.md
- Decisions made: dirty/divergent/missing Desktop repo skips; merge remains successful.
- Commands run: python3 -m pytest tests/test_sync_desktop_main.py -q; python3 -m py_compile scripts/sync_desktop_main.py; bash -n scripts/claude-hooks/stop-ship.sh; python3 scripts/check_doc_links.py --check-all; git diff --check; python3 scripts/sync_desktop_main.py --repo /Users/hskim/Desktop/projects/BidMate-DocAgent
- Results: pass; Desktop main already matches origin/main after manual fast-forward.
- Eval surface: none.
- Open risks: Reviewer should verify branch update cannot discard local work.
- Next action: Run validation and ship.
- Next safe command: python3 -m pytest tests/test_sync_desktop_main.py -q
- Reviewer focus: no reset/destructive behavior, fail-soft Stage 5 behavior.
```

## T-2026-0004 — HWP PDF PyMuPDF4LLM opt-in loader

- ID: T-2026-0004
- Title: HWP PDF PyMuPDF4LLM opt-in loader
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Add an opt-in HWP parser path that converts HWP to PDF and parses the PDF with
PyMuPDF4LLM page chunks, while preserving the ADR 0049 `kordoc` default and
ADR 0001 `csv_text` fallback.

### Context

- Surface: load-bearing ingestion parser.
- Relevant docs: [ADR 0049](../docs/adr/0049-kordoc-replaces-pyhwp-backend.md),
  [HWP extraction comparison](../docs/hwp/hwp-extraction-comparison.md).
- Primary risk: historical LibreOffice HWP conversion failure being reported
  as successful parsing.

### Scope

- Add `BIDMATE_HWP_LOADER=pdf_pymupdf4llm` and matching `--hwp_loader` choice.
- Validate converter output with PyMuPDF before PyMuPDF4LLM parsing.
- Record stable fallback reason keys and redact private path/file details.
- Extend the local comparison script with a PyMuPDF4LLM path.

### Non-Goals

- Do not change the default `kordoc` loader.
- Do not auto-install H2Orestart or other LibreOffice extensions.
- Do not claim real-eval quality without a separate private run.

### Acceptance Criteria

- [x] Default HWP loader remains `HwpKordocLoader`.
- [x] Opt-in loader returns page sections with `page_span` on success.
- [x] Converter/parser failures fall back to CSV text unless required mode is set.
- [x] Required mode raises instead of falling back.
- [x] Focused regression tests cover success and failure modes.

### Validation Commands

```bash
python3 -m unittest tests.test_hwp_pdf_pymupdf4llm_loader -v
python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py -q
python3 -m py_compile ingestion.py scripts/build_index.py scripts/compare_hwp_extraction.py tests/test_hwp_pdf_pymupdf4llm_loader.py
```

### Evidence Required

- Focused unittest output.
- Pytest exit code 0 for existing ingestion regressions plus new loader tests.
- Manual reviewer check that fallback diagnostics do not leak private paths.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md`](../docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md)
- Issue: N/A
- PR: TBD
- ADR: [ADR 0078](../docs/adr/0078-pymupdf4llm-canonical-page-citation.md)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: detached HEAD / /Users/hskim/.codex/worktrees/a32e/BidMate-DocAgent
- Task: T-2026-0004
- Plan: docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md
- Current status: canonical PDF/HWP PyMuPDF4LLM page-citation loader implemented.
- Files touched: ingestion.py, rag_answer.py, rag_indexing.py, rag_retrieval.py, rag_provenance.py, scripts/build_index.py, eval/run_eval.py, requirements-pymupdf4llm.txt, tests, docs/plans, ADR 0078, tasks/queue.md
- Decisions made: default HWP/PDF loader is pdf_pymupdf4llm; HWP citations refer to preserved LibreOffice converted PDF artifacts; parser failures fail closed unless explicit csv_text is selected.
- Commands run: python3 -m unittest tests.test_hwp_pdf_pymupdf4llm_loader -v; python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_provenance_banner.py tests/test_run_eval_by_format_text_source.py tests/test_page_aware_parser_contract.py tests/test_eval_metrics.py tests/test_answer_contract_snapshot.py tests/test_retrieval_loop_regression.py -q; python3 -m ruff check ...; python3 -m py_compile ...; git diff --check; python3 scripts/_governance.py --lint-adr-consequences docs/adr/0078-pymupdf4llm-canonical-page-citation.md; python3 scripts/check_doc_links.py --check-all --paths ...
- Results: pass.
- Eval surface: none; no real-eval quality claim.
- Open risks: actual HWP conversion quality still depends on local LibreOffice HWP filter setup.
- Next safe command: python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_provenance_banner.py tests/test_run_eval_by_format_text_source.py -q
- Reviewer focus: fail-closed parser policy, private path exclusion from answer citations, and page-citation-ready telemetry.
```
