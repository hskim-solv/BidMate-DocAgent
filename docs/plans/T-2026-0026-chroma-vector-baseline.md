# Plan: T-2026-0026 Chroma Vector Baseline

- Status: todo
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0026`
- Related issue / PR: [#1580](https://github.com/hskim-solv/BidMate-DocAgent/issues/1580) / PR TBD

## Problem

Vector DB backend effects are a separate performance axis from embedding model
effects. The current code supports `memory` and `qdrant` only, with ranking
parity expected between them. Chroma is not implemented, so it cannot yet be
used as a baseline.

## Desired Outcome

Add Chroma as an explicit vector-store backend baseline while preserving clear
separation between:

- embedding backend/model: hashing, MiniLM, BGE-M3, OpenAI, etc.
- vector DB backend: memory, qdrant, Chroma.
- retrieval backend: dense, hybrid, metadata-first, etc.

## Scope

- Add `ChromaVectorStore` behind `BIDMATE_INDEX_BACKEND=chroma`.
- Add Chroma install and persistence/connection docs.
- Add ranking parity tests against the in-memory backend.
- Add a reproducible Chroma baseline command or make target.
- Record vector DB backend provenance separately from embedding provenance.

## Out Of Scope

- Do not switch the canonical private real-eval baseline by default.
- Do not combine Chroma with MiniLM/BGE-M3 embedding changes.
- Do not claim quality improvement without paired same-embedding same-corpus
  evidence.

## Validation

```bash
python3 -m pytest -q tests/test_vector_store_chroma.py
python3 -m pytest -q tests/test_vector_store_qdrant.py tests/test_qdrant_integration.py -m "not qdrant_integration"
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0026-chroma-vector-baseline.md
git diff --check
make check-branch
```

## Evidence

- Memory-vs-Chroma ranking parity test output, or an explicit measured ranking
  drift report if Chroma cannot be made bit-identical.
- Provenance sample showing vector DB backend separately from embedding
  backend/model.
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
- Current status: issue created and queue/plan entry captured; implementation
  not started.
- Files touched: `docs/plans/T-2026-0026-chroma-vector-baseline.md`,
  `tasks/queue.md`.
- Commands run: `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0026-chroma-vector-baseline.md`; `git diff --check`; `make check-branch`.
- Results: Chroma baseline is separated as follow-up issue #1580.
- Blockers: none known.
- Open risks: Chroma ranking/tie-break may differ from the in-memory backend;
  Chroma dependency cost may affect CI or local setup.
- Next action: implement Chroma adapter in a separate issue-linked PR.
- Next safe command: `git status --short`
- Reviewer focus: backend axis separation, parity guard, no mixed embedding
  claim.
