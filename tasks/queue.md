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
| 5 | `T-2026-0005` | `review` | Implementer -> Benchmark Auditor -> Reviewer | implementation validated; issue #1493 / branch `feat/issue-1493-rag-eval-first-adapter-hardening`. |
| 6 | `T-2026-0006` | `review` | Implementer -> Reviewer | `ai_next_actions` human-readable HTML review surface 구현됨. |
| 7 | `T-2026-0007` | `review` | Implementer -> Reviewer | failure distribution local HTML board 구현됨. |
| 8 | `T-2026-0008` | `review` | Implementer -> Reviewer | chunking diagnostics local HTML board 구현됨. |
| 9 | `T-2026-0009` | `review` | Implementer -> Reviewer | ADR decision map local HTML board 구현됨. |
| 10 | `T-2026-0010` | `review` | Implementer -> Reviewer | priority aggregate HTML review boards implemented; issue #1518 / branch `chore/issue-1518-priority-html-boards`. |

## Examples

- [`tasks/examples/benchmark-hardening.md`](examples/benchmark-hardening.md): benchmark hardening task 작성 예시.
- [`tasks/examples/eval-regression-safety.md`](examples/eval-regression-safety.md): eval regression safety task 작성 예시.

## T-2026-0010 — Priority HTML review boards

- ID: T-2026-0010
- Title: Priority HTML review boards
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Render the next six aggregate reviewer surfaces as local HTML boards so a human
can inspect current eval/retrieval/governance signals without opening several
JSON and Markdown files.

### Context

- Surface: private real-eval aggregate / public synthetic benchmark docs /
  reviewer workflow.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [`docs/plans/T-2026-0010-priority-html-review-boards.md`](../docs/plans/T-2026-0010-priority-html-review-boards.md).
- Primary risk: HTML summaries accidentally implying a fresh eval run or
  exposing private raw data.

### Scope

- Add a local renderer for six HTML boards.
- Use existing aggregate/redacted JSON and docs only.
- Add focused renderer tests.
- Preserve the operating convention that AI handoff/source-of-truth stays in
  Markdown while human review boards are rendered as HTML.

### Non-Goals

- Do not change RAG runtime, parser runtime, retrieval behavior, or eval scoring.
- Do not read private raw documents or per-case payloads.
- Do not claim performance improvement.

### Acceptance Criteria

- [x] One command writes all six local HTML boards.
- [x] Tests prove escaping and repository-relative source paths.
- [x] Generated HTML is manually smoke-checked through a local HTTP server.

### Validation Commands

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 scripts/render_priority_review_boards.py
git diff --check
```

### Evidence Required

- Focused pytest output.
- Generated HTML paths.
- Browser smoke result.

### Failure Conditions

- Stop if a board needs raw private data.
- Stop if the board would introduce a new benchmark/eval claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0010-priority-html-review-boards.md`](../docs/plans/T-2026-0010-priority-html-review-boards.md)
- Issue: [#1518](https://github.com/hskim-solv/BidMate-DocAgent/issues/1518)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1518-priority-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0010
- Plan: docs/plans/T-2026-0010-priority-html-review-boards.md
- Current status: implemented and validated; PR pending.
- Files touched: CLAUDE.md, tasks/queue.md, docs/plans/T-2026-0010-priority-html-review-boards.md, scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py
- Decisions made: presentation-only renderer; aggregate/redacted inputs only.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 scripts/render_priority_review_boards.py; git diff --check; python3 scripts/check_doc_links.py --check-all; browser smoke via http://127.0.0.1:8765
- Results: six HTML boards generated locally; focused tests, doc links, diff check, and browser smoke pass.
- Validation evidence: local HTTP browser smoke confirmed all six board titles/cards/tables.
- Eval surface: aggregate-only private real-eval plus public docs.
- Open risks: generated HTML files remain ignored local artifacts; script regenerates them.
- Next action: open PR.
- Next safe command: gh pr create
- Reviewer focus: privacy boundary, over-claiming, escaping.
```

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

## T-2026-0005 — Eval-first RAG adapter hardening

- ID: T-2026-0005
- Title: Eval-first RAG adapter hardening
- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Implement the eval-first RAG hardening plan without creating a new `src/rag/*`
tree or changing the `naive_baseline` / answer schema / ADR 0005 boundary.

### Context

- Surface: public fixture smoke eval + eval governance.
- Relevant docs: [ADR 0001](../docs/adr/0001-preserve-naive-baseline.md),
  [ADR 0003](../docs/adr/0003-structured-answer-citation-contract.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0069](../docs/adr/0069-retrieval-aggregate-and-citation-coverage-surface.md),
  [ADR 0074](../docs/adr/0074-rfp-rag-stage-separation.md).
- Primary risk: mixing measurement additions with default behavior changes.

### Scope

- Add LLM-free context precision/recall retrieval metrics.
- Extend run/index version manifest fields additively.
- Add `EmbeddingProvider` Protocol/factory around existing `rag_embedding.py`.
- Add opt-in deterministic contextual chunking while preserving fixed/section defaults.
- Keep Qdrant/pgvector and multimodal expansion as follow-up-only surfaces.

### Non-Goals

- Do not change `naive_baseline`.
- Do not bump answer `schema_version`.
- Do not make HyDE, Self-RAG, Reflexion, CRAG, ColPali, or GPT-VL default.
- Do not send private data to external providers.

### Acceptance Criteria

- [x] `reports/eval_summary.json` can expose context precision/recall aggregates.
- [x] `run_manifest` carries index/chunking/embedding version fields.
- [x] Embedding provider swapping is tested with fake/local providers.
- [x] Contextual chunking is opt-in and regression-tested.
- [x] Focused tests and branch convention checks pass.

### Validation Commands

```bash
python3 -m pytest tests/test_chunk_metrics_regression.py tests/test_chunk_aggregate_regression.py tests/test_run_manifest_versioning_regression.py -q
python3 -m pytest tests/test_embedding_provider_protocol.py tests/test_contextual_chunking_regression.py -q
python3 -m pytest tests/test_vector_store_protocol.py tests/test_vector_store_qdrant.py -q
make check-branch
```

### Evidence Required

- Focused pytest output.
- Smoke/eval summary diff explanation.
- Review note confirming baseline and answer contract unchanged.

### Failure Conditions

- Stop if the implementation requires changing answer dict shape.
- Stop if external provider code would run by default.
- Stop if public fixture smoke is used as a real-world quality claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0005-rag-eval-first-adapter-hardening.md`](../docs/plans/T-2026-0005-rag-eval-first-adapter-hardening.md)
- Issue: [#1493](https://github.com/hskim-solv/BidMate-DocAgent/issues/1493)
- PR: [#1499](https://github.com/hskim-solv/BidMate-DocAgent/pull/1499)
- ADR: ADR 0001, ADR 0003, ADR 0005, ADR 0069, ADR 0074

## T-2026-0006 — Human-readable AI next actions review surface

- ID: T-2026-0006
- Title: Human-readable AI next actions review surface
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give human reviewers a compact local HTML status board for the deterministic
AI next-action planner, without replacing the existing Markdown task briefs.

### Context

- Surface: workflow/reviewer tooling.
- Relevant docs: [`docs/operations/ai-codex-workflow.md`](../docs/operations/ai-codex-workflow.md),
  [`docs/reviews/README.md`](../docs/reviews/README.md).
- Primary risk: dense agent-oriented Markdown being treated as sufficient for
  human triage, or local generated HTML being mistaken for PR evidence.

### Scope

- Add `reports/ai_next_actions.html` as a generated local artifact.
- Keep `reports/ai_next_actions.md` and `reports/codex_tasks/*.md` behavior.
- Document that the HTML is a status board, not approval evidence.

### Non-Goals

- Do not change retrieval, verifier, answer, eval, or private-data behavior.
- Do not introduce JavaScript, external services, or new runtime dependencies.
- Do not publish local `reports/*` artifacts.

### Acceptance Criteria

- [x] Planner emits Markdown, task briefs, and self-contained HTML from one
  deterministic work-item model.
- [x] HTML escapes PR/user-provided text and does not leak forbidden private
  readiness fields.
- [x] HTML output can be disabled with `--out-html ""`.
- [x] Reviewer docs explain how to use the local status board.

### Validation Commands

```bash
python3 -m py_compile scripts/ai_next_actions.py
python3 -m pytest -q tests/test_ai_next_actions.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Manual note if browser visual verification is unavailable.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0006-human-review-surface.md`](../docs/plans/T-2026-0006-human-review-surface.md)
- Issue: [#1506](https://github.com/hskim-solv/BidMate-DocAgent/issues/1506)
- PR: TBD
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1506-human-review-surface / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0006
- Plan: docs/plans/T-2026-0006-human-review-surface.md
- Current status: HTML review surface implemented on top of scripts/ai_next_actions.py.
- Files touched: scripts/ai_next_actions.py, tests/test_ai_next_actions.py, docs/operations/ai-codex-workflow.md, docs/reviews/README.md, tasks/queue.md, docs/plans/T-2026-0006-human-review-surface.md
- Decisions made: Generate a self-contained local HTML file next to the existing Markdown output; keep source-of-truth logic in WorkItem classification and keep HTML non-evidence.
- Commands run: python3 -m py_compile scripts/ai_next_actions.py; python3 -m pytest -q tests/test_ai_next_actions.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch
- Results: pass, except browser file:// visual verification was blocked by app URL policy.
- Eval surface: none.
- Open risks: reviewer should inspect whether the inline HTML/CSS is acceptable for a local-only generated report.
- Next safe command: python3 -m pytest -q tests/test_ai_next_actions.py
- Reviewer focus: privacy-safe rendering, deterministic output, and no evidence over-claim.
```

## T-2026-0007 — Human-readable failure case board

- ID: T-2026-0007
- Title: Human-readable failure case board
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML view of failure-mode distribution and
per-category slices without replacing the committed Markdown/aggregate JSON
evidence.

### Context

- Surface: private real-eval aggregate viewer.
- Relevant docs: [`docs/operations/failure-mode-harden-process.md`](../docs/operations/failure-mode-harden-process.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0075](../docs/adr/0075-normalized-failure-taxonomy.md).
- Primary risk: raw private query/doc strings leaking into a human-facing local
  report, or HTML being mistaken for model-quality evidence.

### Scope

- Add `reports/real100/failure_distribution.html` as a generated local artifact.
- Keep `reports/real100/failure_distribution.md` and
  `reports/real100/failure_distribution.aggregate.json` behavior unchanged.
- Add a small shared HTML report shell for future local report surfaces.

### Non-Goals

- Do not change failure classifier ordering, taxonomy, eval scoring, retrieval,
  verifier, answer generation, or private raw data.
- Do not introduce JavaScript, external services, or runtime dependencies.
- Do not publish local HTML artifacts.

### Acceptance Criteria

- [x] Renderer emits Markdown, aggregate JSON, and self-contained HTML by default.
- [x] HTML output can be disabled with `--out-html ""`.
- [x] HTML escapes dynamic text and does not leak raw query/doc strings.
- [x] Existing aggregate schema remains unchanged.
- [x] Workflow docs mention the local HTML dashboard.

### Validation Commands

```bash
python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py
python3 -m pytest -q tests/test_render_failure_distribution.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0007-failure-case-board.md tasks/queue.md docs/operations/failure-mode-harden-process.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that no real-eval performance claim is made.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0007-failure-case-board.md`](../docs/plans/T-2026-0007-failure-case-board.md)
- Issue: [#1510](https://github.com/hskim-solv/BidMate-DocAgent/issues/1510)
- PR: TBD
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1510-failure-case-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0007
- Plan: docs/plans/T-2026-0007-failure-case-board.md
- Current status: HTML failure board implemented on top of scripts/render_failure_distribution.py.
- Files touched: scripts/html_report.py, scripts/render_failure_distribution.py, tests/test_render_failure_distribution.py, docs/operations/failure-mode-harden-process.md, tasks/queue.md, docs/plans/T-2026-0007-failure-case-board.md
- Decisions made: Generate a self-contained local HTML file next to the existing Markdown/aggregate JSON output; keep source-of-truth classification in build_aggregate and failure_classifier.
- Commands run: python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py; python3 -m pytest -q tests/test_render_failure_distribution.py; git diff --check
- Results: pass.
- Eval surface: private real-eval aggregate viewer only.
- Open risks: reviewer should inspect whether a later PR should migrate ai_next_actions HTML to the shared shell.
- Next safe command: python3 -m pytest -q tests/test_render_failure_distribution.py
- Reviewer focus: privacy-safe rendering, aggregate-only data boundary, and no evidence over-claim.
```

## T-2026-0008 — Human-readable chunking diagnostics board

- ID: T-2026-0008
- Title: Human-readable chunking diagnostics board
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML view of Phase 2 chunking ablation, real100
chunk health, and multi-chunk evidence failure diagnostics without changing
retrieval or chunking behavior.

### Context

- Surface: private real-eval aggregate viewer plus existing Phase 2 retrieval
  aggregate report.
- Relevant docs: [`docs/retrieval/chunking-diagnostics.md`](../docs/retrieval/chunking-diagnostics.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0076](../docs/adr/0076-multi-chunk-evidence-failure-analysis-surface.md).
- Primary risk: a diagnostic board being mistaken for a chunking winner claim,
  or per-case identifiers/text leaking into local HTML.

### Scope

- Add `reports/retrieval/chunking_diagnostics.html` as a generated local artifact.
- Read existing aggregate or aggregate-derived artifacts only.
- Keep Phase 2 report files and real100 aggregate files unchanged.

### Non-Goals

- Do not change chunking defaults, retrieval, verifier, answer generation, eval
  scoring, or private raw data.
- Do not introduce JavaScript, external services, or runtime dependencies.
- Do not publish local HTML artifacts.

### Acceptance Criteria

- [x] Renderer emits a self-contained local HTML board.
- [x] HTML includes chunking variants, recall@10 deltas, chunk health, and
  multi-chunk retrieval outcome counts.
- [x] HTML does not render private case ids from per-case inputs.
- [x] Existing retrieval/chunking/eval behavior remains unchanged.

### Validation Commands

```bash
python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py
python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0008-chunking-diagnostics-board.md tasks/queue.md docs/retrieval/chunking-diagnostics.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that no chunking winner or RAG quality claim is made.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0008-chunking-diagnostics-board.md`](../docs/plans/T-2026-0008-chunking-diagnostics-board.md)
- Issue: [#1514](https://github.com/hskim-solv/BidMate-DocAgent/issues/1514)
- PR: TBD
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1514-chunking-diagnostics-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0008
- Plan: docs/plans/T-2026-0008-chunking-diagnostics-board.md
- Current status: HTML chunking diagnostics board implemented.
- Files touched: scripts/render_chunking_diagnostics_board.py, tests/test_render_chunking_diagnostics_board.py, docs/retrieval/chunking-diagnostics.md, tasks/queue.md, docs/plans/T-2026-0008-chunking-diagnostics-board.md
- Decisions made: Generate a self-contained local HTML file from existing aggregate artifacts; do not claim a chunking winner.
- Commands run: python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py; python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py; git diff --check
- Results: pass.
- Eval surface: private real-eval aggregate viewer plus existing Phase 2 retrieval aggregate report.
- Open risks: reviewer should inspect claim wording and whether additional slices belong in a separate follow-up.
- Next safe command: python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py
- Reviewer focus: claim boundary, aggregate-only rendering, and no default behavior change.
```

## T-2026-0009 — Human-readable ADR decision map

- ID: T-2026-0009
- Title: Human-readable ADR decision map
- Status: review
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML map of ADR status mix, decision areas,
recent ADRs, proposed ADRs, and superseded decisions without editing ADR source
files.

### Context

- Surface: ADR navigation/reviewer tooling.
- Relevant docs: [`docs/adr/README.md`](../docs/adr/README.md).
- Primary risk: a generated HTML view being mistaken for the ADR source of
  truth, or keyword-based area grouping being treated as governance logic.

### Scope

- Add `reports/adr_decision_map.html` as a generated local artifact.
- Parse existing `docs/adr/README.md` rows.
- Keep ADR files, statuses, numbering, and README content unchanged.

### Non-Goals

- Do not create or edit ADRs.
- Do not reserve ADR numbers.
- Do not promote/demote statuses or enforce lifecycle policy.
- Do not introduce JavaScript, external services, or runtime dependencies.

### Acceptance Criteria

- [x] Renderer emits a self-contained local HTML board.
- [x] HTML includes status mix, decision areas, recent ADRs, proposed ADRs, and
  superseded decisions.
- [x] Tests verify canonical row parsing, status counts, and escaping.
- [x] ADR source files remain unmodified.

### Validation Commands

```bash
python3 scripts/render_adr_decision_map.py
python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py
python3 -m pytest -q tests/test_render_adr_decision_map.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0009-adr-decision-map.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that `docs/adr/README.md` and ADR files are unchanged.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0009-adr-decision-map.md`](../docs/plans/T-2026-0009-adr-decision-map.md)
- Issue: [#1516](https://github.com/hskim-solv/BidMate-DocAgent/issues/1516)
- PR: TBD
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1516-adr-decision-map / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0009
- Plan: docs/plans/T-2026-0009-adr-decision-map.md
- Current status: HTML ADR decision map implemented.
- Files touched: scripts/render_adr_decision_map.py, tests/test_render_adr_decision_map.py, tasks/queue.md, docs/plans/T-2026-0009-adr-decision-map.md
- Decisions made: Generate a self-contained local HTML file from docs/adr/README.md only; keep ADR source files unchanged.
- Commands run: python3 scripts/render_adr_decision_map.py; python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py; python3 -m pytest -q tests/test_render_adr_decision_map.py; git diff --check
- Results: pass.
- Eval surface: none.
- Open risks: reviewer should inspect that area grouping is navigation-only.
- Next safe command: python3 -m pytest -q tests/test_render_adr_decision_map.py
- Reviewer focus: source-of-truth wording, parser robustness, and escaping.
```
