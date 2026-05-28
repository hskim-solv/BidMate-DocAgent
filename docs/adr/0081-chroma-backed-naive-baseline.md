# 0081: Chroma-backed naive baseline

- **Status**: accepted
- **Date**: 2026-05-28
- **Deciders**: maintainer
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0020](./0020-protocol-based-pluggability.md), [issue #1580](https://github.com/hskim-solv/BidMate-DocAgent/issues/1580)

## Context

ADR 0001 keeps `naive_baseline` as the side-by-side control for the agentic
pipeline. That contract previously covered the retrieval algorithm but left the
vector DB backend implicit through `BIDMATE_INDEX_BACKEND`, whose default was
the local numpy-backed `memory` store.

Vector DB backend effects are a separate axis from embedding model effects.
Issue #1580 tracks Chroma as the desired baseline vector-store candidate, while
MiniLM/BGE-M3 and other semantic embedding comparisons remain separate work.

## Decision

`naive_baseline` is now a Chroma-backed baseline: its pipeline config declares
`vector_store_backend: chroma`, and the zero-env `BIDMATE_INDEX_BACKEND`
default is `chroma`.

The retrieval algorithm remains dense-only, fixed top-k, no metadata-first, no
rerank, no verifier retry. `memory` remains an explicit legacy/control backend,
and `qdrant` remains an ops comparison backend. Private aggregate baseline
refresh is a separate follow-up after the Chroma-backed contract lands.

## Consequences

- Chroma becomes a base dependency because the default local path must run
  without optional install steps.
- Eval summaries and deltas must carry `vector_store_backend` separately from
  embedding backend/model provenance.
- A single eval config cannot mix vector-store backends; backend comparisons
  must run as separate commands with comparable config/index provenance.
- Chroma must match the memory backend's top-k ranking on parity tests. Ranking
  drift is not accepted as a completed canonical switch.

## Alternatives considered

- Keep Chroma opt-in only. Rejected because the chosen baseline contract is
  canonical, not just a backend candidate.
- Regenerate committed private baselines in the same PR. Rejected to keep the
  implementation contract separate from aggregate metric refresh and privacy
  review.
- Fold vector-store backend into retrieval backend. Rejected because
  `retrieval_backend=dense|hybrid|m3|random` describes ranking strategy, not
  vector DB storage/query infrastructure.

## Verification

<!-- verifies-key: rag_pipeline_presets.py:vector_store_backend -->
<!-- verifies-key: rag_vector_store.py:DEFAULT_INDEX_BACKEND = "chroma" -->
<!-- verifies-key: tests/test_vector_store_chroma.py:test_chroma_query_matches_in_memory_top_k_ranking -->
<!-- verifies-key: eval/run_eval.py:vector_store_backend_for_runs -->
