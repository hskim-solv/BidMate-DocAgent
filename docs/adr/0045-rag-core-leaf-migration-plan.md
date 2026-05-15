# 0045: rag_core leaf migration plan — embedding helpers + comparison_targets routing

- **Status**: accepted
- **Date**: 2026-05-15
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) · CLAUDE.md
  *Repository map* (rag_retrieval / rag_verifier / rag_answer / rag_query
  decomposition) · issue #762
- **Deciders**: hskim

## Context

`rag_core.py` is 1728 LOC.  PR-H1a/b (issue #459 / #461) and PR-J1/J2/J3
(issue #465 / #468 / #478) extracted retrieval / verifier / answer /
query into sibling leaf modules, but the import graph is still not
clean: `rag_retrieval.py` reaches back into `rag_core` from inside two
functions via late-import.

### Observed late-import inventory (2026-05-15, branch `main`)

| Call site | Late-imported symbols |
|-----------|----------------------|
| [`rag_retrieval.py:168`](../../rag_retrieval.py:168) | `comparison_targets_for_analysis` |
| [`rag_retrieval.py:490`](../../rag_retrieval.py:490) | `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`, `embed_texts`, `hashing_embeddings` |

Two call sites × five symbols.  The other three split modules are
already top-level-clean:

- `rag_query.py`, `rag_verifier.py`, `rag_answer.py` — **zero** rag_core
  imports (top-level or late).

CLAUDE.md itself acknowledges the unfinished state:

> *"`rag_core.py` is still orchestration + many utilities → late-import
> for cycle avoidance (not a leaf in the dependency graph)."*

This ADR plans the cleanup. Actual code migration is **out of scope**
for this ADR — it lands as a separate PR (`G2` in the GEF loop, tracked
in `/Users/hskim/.claude/plans/gleaming-forging-dove.md`).

### Why two distinct migrations, not one

The five late-imported symbols split into two semantic groups:

1. **Embedding primitives** — `embed_texts`, `hashing_embeddings`,
   `_embed_with_openai`, `sentence_transformer_cache_available`,
   `huggingface_offline`, `expand_features`, `EmbeddingResult`,
   `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`.  These are used by
   `rag_retrieval.embed_query_for_index`, `rag_core` index-build,
   *and* `scripts/build_index.py` — three independent consumers.  They
   are not retrieval-specific.
2. **Query-analysis output reader** — `comparison_targets_for_analysis`
   is **already defined in `rag_query.py:397`** as part of the PR-J3
   extraction; `rag_core` only re-exports it.  The late-import in
   retrieval is therefore a stale routing decision, not a missing
   home.

These have different fixes (new leaf module vs. import-source change),
so they belong in separate PRs.

## Decision

### Plan A: embedding primitives → new leaf module `rag_embedding.py`

Create `rag_embedding.py` as a sibling leaf, modeled on the existing
[`rag_text_processing.py`](../../rag_text_processing.py) /
[`rag_metadata_processing.py`](../../rag_metadata_processing.py)
pattern.  Move:

- Constants: `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`
- Dataclasses: `EmbeddingResult`
- Functions: `embed_texts`, `_embed_with_openai`,
  `sentence_transformer_cache_available`, `huggingface_offline`,
  `hashing_embeddings`, `expand_features`

Update consumers:

- `rag_core.py` — top-level `from rag_embedding import …`; keep
  re-export aliases so downstream code (tests, eval scripts) does not
  break.
- `rag_retrieval.py` — replace the late-import block with a top-level
  `from rag_embedding import …`.
- `scripts/build_index.py` — replace `from rag_core import
  DEFAULT_EMBEDDING_MODEL` with `from rag_embedding import …`.

### Plan B: comparison_targets routing

In `rag_retrieval.py:168`, change the late-import to a top-level import
from `rag_query`:

```python
# old:
from rag_core import comparison_targets_for_analysis  # inside function
# new (top-level):
from rag_query import comparison_targets_for_analysis
```

Verified direction-safe (2026-05-15):

```
$ grep -nE "^from rag_|^import rag_" rag_query.py
# (no reference to rag_retrieval)
```

`rag_query` is already a leaf; `rag_retrieval → rag_query` is therefore
a clean DAG edge.

### Sequencing

- Plan B is a **2-line change** (1 import move + 1 deleted late-import).
  Bundled into the same PR as Plan A is acceptable since both target
  the same file (`rag_retrieval.py`) and both eliminate the same
  `rag_core` back-edge.
- Plan A + B together = the G2 PR.

## Alternatives considered

### (a) Move embedding primitives into `rag_retrieval.py`

*Rejected*: `scripts/build_index.py` does not need retrieval and
should not pay the import cost of cross-encoder rerankers, query
expanders, etc.  Embedding primitives are not retrieval-specific.

### (b) Leave `rag_core` as the canonical home, document the late-import as accepted

*Rejected*: CLAUDE.md already calls this out as unfinished work.  The
late-import works at runtime but defeats static analysis (IDE
go-to-definition, mypy reachability) and signals architectural debt to
new contributors.  This is a senior-portfolio readability cost.

### (c) Single big-bang migration that also splits text/metadata helpers

*Rejected*: text/metadata helpers are *already* extracted (`rag_text_processing.py`, `rag_metadata_processing.py`).  Bundling
embedding migration with non-existent further splits inflates the
diff without benefit.  One concern per PR (CLAUDE.md).

### (d) Use Python `__all__` / re-export instead of an actual move

*Rejected*: re-export does not break the cycle; rag_core still owns
the function bodies.  The whole point is to make `rag_core` thin.

## Consequences

**Wins**

- `rag_retrieval.py` becomes a true leaf w.r.t. `rag_core` — no
  back-edges.
- `rag_core.py` shrinks by ~150 LOC (the embedding block).  Step
  toward the ~600-LOC orchestration-only target named in the GEF loop.
- `scripts/build_index.py` no longer needs rag_core to embed — index
  build can in principle run without loading the full retrieval/answer
  stack.
- IDE / static analyzers report the true dependency graph.

**Costs**

- One new module file to maintain.  Mitigated: it follows the existing
  `rag_*_processing.py` pattern, so onboarding cost is near zero.
- Re-export aliases in `rag_core` are dead weight from a graph
  cleanliness perspective.  They are **kept on purpose** for the first
  migration to avoid breaking eval scripts; a follow-up ADR may
  schedule their removal once import sites are audited.

**Unchanged**

- ADR 0001 naive-baseline invariant: `embed_texts` /
  `hashing_embeddings` semantics are byte-identical after the move —
  G2 PR is a pure relocation, not a logic change.
- ADR 0003 answer contract: untouched (answer generation does not
  embed).
- `EMBEDDING_BACKEND` env contract: unchanged (the env-var dispatch
  lives inside `embed_texts`, which moves as-is).

### Out of scope for this ADR

- Further `rag_core` slim-down beyond embedding (ingestion split,
  `_RunContext` re-housing) — covered by G3 in the GEF plan.
- Removing the re-export shims in `rag_core` — scheduled for after
  G4 dependency-graph verification.
- pgvector / Qdrant adapter implementations — F1/F2 in the GEF plan.

## Verification

This ADR is plan-only.  The two preconditions it asserts must be present
in the working tree at PR time (G2 verifies their *removal* after the
code move):

<!-- verifies-key: rag_retrieval.py:from rag_core import -->
<!-- verifies-key: rag_query.py:def comparison_targets_for_analysis -->

The G2 implementation PR must show:

1. `make smoke` passes (`EMBEDDING_BACKEND=hashing`, hashing path used)
2. `bash scripts/test.sh` passes (full pytest)
3. `make real-eval-delta` shows §5b parity (this ADR's invariant is
   *bit-identical embeddings* — any delta is a bug)
4. `git grep -nE "^\s+from rag_core" rag_retrieval.py rag_query.py rag_verifier.py rag_answer.py` returns **zero** lines
5. ADR 0001 `naive_baseline` preset golden unchanged
