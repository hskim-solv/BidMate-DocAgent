# 0020: Protocol-based pluggability for retrieval-side extension points

- **Status**: accepted
- **Date**: 2026-05-13
- **Related**: [ADR 0013](0013-observability-as-additive-pluggable-surface.md) (additive pluggability theme), [PR #234](https://github.com/hskim-solv/BidMate-DocAgent/pull/234) (VectorStore Stage 1), [PR #358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358) (Reranker), [issue #176](https://github.com/hskim-solv/BidMate-DocAgent/issues/176) (VectorStore work), [issue #345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345) (Reranker work), [`rag_vector_store.py`](../../rag_vector_store.py), [`rag_reranker.py`](../../rag_reranker.py)

## Context

Two independent Phase 2 refactors introduced structurally identical patterns
without a shared architectural rationale:

**VectorStore Protocol** (issue #176, PR #234 + follow-ups #288 / #296 / #326):
`rag_vector_store.py` exposes a `@runtime_checkable typing.Protocol` (VectorStore)
with `InMemoryVectorStore` as the default and `QdrantVectorStore` as an adapter.
`BIDMATE_INDEX_BACKEND` drives dispatch; `rag_core.py` is untouched when a new
backend registers.

**Reranker Protocol** (issue #345, PR #358):
`rag_reranker.py` mirrors the same shape — `@runtime_checkable` Protocol,
`CrossEncoderReranker` default adapter wrapping `rag_rerank.rerank`, and a
`default_reranker()` factory as the single wiring hook. Future rerankers
(HyDE, LLM-as-judge) plug in here; `rag_core.py` is untouched.

The convention recurs naturally in Phase 3 (HyDE query expansion, alternative
embedding backends, multi-query retrieval). Without a written ADR each future
Protocol PR re-litigates the same design questions: ABC vs Protocol, factory
vs direct import, env-var vs plan-dict routing.

The ADR threshold from [`docs/adr/README.md`](README.md): *"Establishes a new
convention that future changes must follow."* Both PRs already merged; this ADR
converts the implicit convention into an explicit reference.

## Decision

Retrieval-side extension points follow a four-property convention:

1. **`@runtime_checkable typing.Protocol` in a leaf module.**
   The Protocol lives in its own file (`rag_<aspect>.py`) so the
   dependency graph stays acyclic. `runtime_checkable` enables
   `isinstance` guards in tests without coupling to a concrete type.

2. **Default adapter wraps the existing implementation.**
   The first concrete class in the new module (`InMemoryVectorStore`,
   `CrossEncoderReranker`) delegates to the existing code path, keeping
   the observable behaviour bit-identical. No eval regression on merge.

3. **`default_<aspect>()` factory as the single dispatch hook.**
   Orchestration code (`rag_core.py`, `rag_retrieval.py`) calls
   `default_reranker()` / `default_vector_store()` exactly once.
   Adding a second implementation requires changing one function in
   one file; retrieval orchestration stays untouched.

4. **Env-var routing inside the factory; plan-dict routing is out of scope.**
   `BIDMATE_INDEX_BACKEND`, `BIDMATE_RERANK_BACKEND` are the dispatch
   signals. The plan dict produced by `analyze_query` is for query-level
   decisions; backend selection is environment-level configuration.

## Consequences

**Easier:**
- New extension point (e.g. `QueryExpander`, `EmbeddingBackend`) follows
  the same four steps. PR reviewer can cite this ADR instead of re-examining
  the pattern from scratch.
- `isinstance(x, VectorStore)` and `isinstance(x, Reranker)` work in tests
  for structural duck-typing checks.
- Eval is unaffected at merge: the default adapter wraps the existing code
  path, so `naive_baseline` stays bit-identical (ADR 0001 invariant).

**Harder / constrained:**
- Ceremony cost: a new retrieval-side extension point requires a new leaf
  module (Protocol + default class + factory), not just a new function.
  Reversal cost is low — each leaf module is independent.
- `@runtime_checkable` Protocols do not check method signatures at
  `isinstance` time, only presence. Full type safety requires `mypy`
  structural checking, not runtime guards alone.

**Follow-up precedent already set:**
- `rag_query_expansion.py` (ADR 0023) introduces `QueryExpander` using
  the same four-property convention, citing this pattern.
- Phase 3 HyDE, LLM-as-reranker, and alternative embedding backends are
  expected to follow the same shape.

## Alternatives considered

- **ABC (`abc.ABC` + `@abstractmethod`) instead of Protocol**: ABCs require
  concrete classes to register or inherit, coupling the extension point to
  the base class. Protocols work structurally — any class with the right
  methods satisfies the contract without importing from this module.
  Chosen: Protocol.

- **Factory-free direct import**: callers import the concrete class directly.
  Rejected: changes the import site in orchestration code whenever the default
  class changes. The factory pattern (one import, one call site) makes
  future swaps transparent.

- **Plan-dict routing**: the query-analysis plan dict selects the backend per
  request. Rejected for backend selection: backends are environment-level
  configuration (cost, availability), not per-query decisions. Plan-dict
  routing is correct for *retrieval mode* (flat vs hierarchical, ADR 0002)
  but not for *infrastructure wiring*.
