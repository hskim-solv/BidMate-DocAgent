# 0010: Hybrid BM25 + dense retrieval with RRF fusion

(Originally landed as ADR 0009 in [#159](https://github.com/hskim-solv/BidMate-DocAgent/pull/159); renumbered to 0010 to resolve a filesystem collision with the concurrent [`0009-external-baseline-comparison.md`](./0009-external-baseline-comparison.md) which landed first.)

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_core.py`](../../rag_core.py), [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0002](0002-metadata-first-retrieval.md), issue #119

## Context

Retrieval today is `dense + lexical (Jaccard token overlap + topic
substring) + metadata` weighted at [`rag_core.py:1832`](../../rag_core.py:1832).
The lexical scorer is set-overlap only — no term frequency, no IDF —
so it under-weights exact matches on rare-but-decisive terms that
dominate Korean RFP queries: 법령명, 사업 코드, 기관 약칭, 사업
식별번호. Dense alone collides on these in the hashing fallback and is
diluted by paraphrastic neighbours under MiniLM. ADR 0002 anchored the
*entity* axis (metadata-first); the *term* axis is still open.

BM25 is the long-standing lexical-match baseline; RRF (Reciprocal
Rank Fusion) combines two heterogeneous-scale rankings without
score-scale normalization. Both are well-understood, deterministic,
and add no model dependency. BGE-M3-style learned sparse retrieval
would also close this gap, but it changes the embedding model
simultaneously — a confound the issue's risks section calls out and
defers to its own ablation.

## Decision

Add an orthogonal pipeline knob `retrieval_backend` with values
`{"dense", "hybrid"}`, default `"dense"` on both presets. When
`"hybrid"`, retrieval ranks candidates by both dense cosine and BM25
(over the chunk-token corpus already in `index.json`), then fuses with
RRF using `k=60`:

> `score = 1/(60 + rank_dense) + 1/(60 + rank_bm25)`

The existing `dense + lexical + metadata` weighted path is preserved
verbatim for `retrieval_backend == "dense"`. BM25 reuses the regex
tokenizer at [`rag_core.py:450`](../../rag_core.py:450) (no KoNLPy, per
prior decision); the `BM25Okapi` index is built lazily and cached on
the index object (`index["_bm25"]`), so `index.json` schema is
unchanged. Diagnostic fields `bm25` and `rank_rrf` are added to
`score_parts` alongside the existing `dense/lexical/metadata`.

## Consequences

**Wins**

- Closes the lexical-match gap for rare-term queries
  (사업 코드, 약칭, 외래어/한자 표기) without paying for a new model.
- `retrieval_backend` is orthogonal to `retrieval_mode`
  (flat/hierarchical, ADR 0002) and to `metadata_first`, so it can be
  ablated cleanly as a new row alongside the existing six.
- Default `"dense"` preserves `naive_baseline` bit-for-bit, satisfying
  ADR 0001.
- RRF avoids the score-scale tuning that a weighted fusion would
  introduce (dense ∈ [0,1] vs BM25 ∈ [0,∞)).

**Costs**

- New dependency `rank_bm25` (pure-Python, MIT). One additional pip
  install in CI and demo environments.
- Lazy BM25 build adds ~O(N·avg_tokens) at first query against an
  index; cached for the lifetime of the index object.
- `score_parts` schema grows by two keys. This is a *diagnostic*
  field, not part of the ADR 0003 answer contract, so no
  `schema_version` bump is required.

## Alternatives considered

- **BGE-M3 sparse channel** — would close the same gap and bring
  multi-vector representations along. Rejected for *this* ADR because
  it bundles an embedding-model swap; deferred to a separate ablation
  so the BM25 contribution is measurable in isolation.
- **Weighted dense + BM25 fusion** — viable but requires choosing and
  defending two weights across heterogeneous score scales. RRF
  removes that tuning surface entirely; if RRF proves too coarse, a
  follow-up RRF-k sweep is cheaper than re-tuning weights.
- **Replacing the existing Jaccard lexical scorer with BM25** —
  rejected: it would silently change `naive_baseline` behaviour
  (ADR 0001 violation) and make the BM25 effect inseparable from the
  preserved-baseline contract.
- **SPLADE / ColBERT late interaction** — out of scope; revisit if
  hybrid_bm25 still leaves a measurable real-data gap.
