# Plan: T-2026-0026 Chroma-Backed Naive Baseline

- Status: in_progress
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0026`
- Related issue / PR: [#1580](https://github.com/hskim-solv/BidMate-DocAgent/issues/1580) / PR TBD

## Problem

Vector DB backend effects are a separate performance axis from embedding model
effects. The previous code supported `memory` and `qdrant` only, with ranking
parity expected between them. Chroma is now the chosen canonical vector-store
backend for `naive_baseline`.

## Desired Outcome

Add Chroma as the Chroma-backed `naive_baseline` vector-store backend while
preserving clear separation between:

- embedding backend/model: hashing, MiniLM, BGE-M3, OpenAI, etc.
- vector DB backend: memory, qdrant, Chroma.
- retrieval backend: dense, hybrid, metadata-first, etc.

## Scope

- Add `ChromaVectorStore` behind `BIDMATE_INDEX_BACKEND=chroma`.
- Make Chroma the zero-env/default vector-store backend.
- Add Chroma install and persistence/connection docs.
- Add ranking parity tests against the in-memory backend.
- Add a reproducible Chroma baseline make target.
- Add `vector_store_backend` to pipeline/eval provenance.
- Record vector DB backend provenance separately from embedding provenance.

## Out Of Scope

- Do not refresh committed private real-eval aggregate baselines in this PR.
- Do not combine Chroma with MiniLM/BGE-M3 embedding changes.
- Do not claim quality improvement without paired same-embedding same-corpus
  evidence.

## Validation

```bash
python3 -m pytest -q tests/test_vector_store_chroma.py tests/test_vector_store_protocol.py
python3 -m pytest -q tests/test_naive_baseline_ranking_invariance.py tests/test_api_default_pipeline_regression.py
python3 -m pytest -q tests/test_vector_store_qdrant.py tests/test_qdrant_integration.py -m "not qdrant_integration"
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0026-chroma-vector-baseline.md
git diff --check
make check-branch
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-chroma
```

## Evidence

- Memory-vs-Chroma ranking parity test output, or an explicit measured ranking
  drift report if Chroma cannot be made bit-identical.
- Provenance sample showing vector DB backend separately from embedding
  backend/model.
- `make real-eval-v2-chroma` writes Chroma output to
  `reports/real100_v2_chroma/` by default, not to the committed baseline
  aggregate path.
- No private raw artifact or exact local path in committed reports.

## Reviewer Focus

- Confirm vector DB backend and embedding model effects are not mixed.
- Confirm parity tests cover ranking and tie-break behavior.
- Confirm Chroma dependency/setup does not make default offline workflows
  heavier.

## Session Handoff

- Role: Planner
- Lifecycle stage: todo
- Branch / worktree: `docs/issue-1580-chroma-vector-baseline-plan` / Codex worktree
- Current status: implementation in progress for the canonical Chroma-backed
  `naive_baseline` contract.
- Files touched: implementation, tests, ADR/docs, queue.
- Commands run: `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0026-chroma-vector-baseline.md`; `git diff --check`; `make check-branch`.
- Results: pending validation in implementation PR.
- Blockers: none known.
- Open risks: Chroma ranking/tie-break may differ from the in-memory backend;
  Chroma dependency cost may affect CI or local setup.
- Next action: complete validation and record PR evidence without refreshing
  private baseline aggregates.
- Next safe command: `git status --short`
- Reviewer focus: backend axis separation, parity guard, no mixed embedding
  claim.
