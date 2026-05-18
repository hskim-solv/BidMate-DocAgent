# Phase 3 retrieval-eval — mode ablation (real100 n=221)

Run: `20260518-0352-phase3-mode` · commit `7aaa6a3931` · index_dir=`/Users/hskim/Desktop/projects/BidMate-DocAgent/data/index/real100` · eval_config=`/Users/hskim/Desktop/projects/BidMate-DocAgent/eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## Variants

| Variant | Backend | RRF k | Docs | Chunks |
|---|---|---|---|---|
| `dense` | dense | — | 100 | 26376 |
| `hybrid_bm25_k30` | hybrid | 30 | 100 | 26376 |
| `hybrid_bm25_k60` | hybrid | 60 | 100 | 26376 |
| `hybrid_bm25_k100` | hybrid | 100 | 100 | 26376 |

## Latency (ms)

| Variant | p50 | p95 | mean | n |
|---|---|---|---|---|
| `dense` | 1270.701 | 3214.817 | 1551.449 | 221 |
| `hybrid_bm25_k30` | 1535.016 | 4130.334 | 1851.968 | 221 |
| `hybrid_bm25_k60` | 1655.319 | 3940.831 | 1980.017 | 221 |
| `hybrid_bm25_k100` | 1604.841 | 4653.97 | 1966.366 | 221 |

## chunk_recall@5

| Category | `dense` | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|---|
| overall | 0.055 (n=114) | 0.018 (n=114) | 0.018 (n=114) | 0.018 (n=114) |
| multi_hop | 0.056 (n=93) | 0.000 (n=93) | 0.000 (n=93) | 0.000 (n=93) |
| distractor_heavy | 0.083 (n=42) | 0.000 (n=42) | 0.000 (n=42) | 0.000 (n=42) |
| long_context | 0.038 (n=9) | 0.000 (n=9) | 0.000 (n=9) | 0.000 (n=9) |
| no_answer | 0.000 (n=2) | 0.000 (n=2) | 0.000 (n=2) | 0.000 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.080 (n=13) | 0.154 (n=13) | 0.154 (n=13) | 0.154 (n=13) |

### chunk_recall@5 — paired CI delta vs `dense` (seed-averaged)

| Category | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|
| overall | -0.037 (-0.074, -0.003) significant | -0.037 (-0.074, -0.003) significant | -0.037 (-0.074, -0.003) significant |
| multi_hop | -0.056 (-0.094, -0.025) significant | -0.056 (-0.094, -0.025) significant | -0.056 (-0.094, -0.025) significant |
| distractor_heavy | -0.083 (-0.157, -0.023) significant | -0.083 (-0.157, -0.023) significant | -0.083 (-0.157, -0.023) significant |
| long_context | -0.038 (-0.113, +0.000) **NOT SIGNIFICANT** | -0.038 (-0.113, +0.000) **NOT SIGNIFICANT** | -0.038 (-0.113, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.074 (-0.080, +0.268) **NOT SIGNIFICANT** | +0.074 (-0.080, +0.268) **NOT SIGNIFICANT** | +0.074 (-0.080, +0.268) **NOT SIGNIFICANT** |

## chunk_recall@10

| Category | `dense` | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|---|
| overall | 0.064 (n=114) | 0.018 (n=114) | 0.018 (n=114) | 0.018 (n=114) |
| multi_hop | 0.067 (n=93) | 0.000 (n=93) | 0.000 (n=93) | 0.000 (n=93) |
| distractor_heavy | 0.087 (n=42) | 0.000 (n=42) | 0.000 (n=42) | 0.000 (n=42) |
| long_context | 0.094 (n=9) | 0.000 (n=9) | 0.000 (n=9) | 0.000 (n=9) |
| no_answer | 0.050 (n=2) | 0.000 (n=2) | 0.000 (n=2) | 0.000 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.081 (n=13) | 0.154 (n=13) | 0.154 (n=13) | 0.154 (n=13) |

### chunk_recall@10 — paired CI delta vs `dense` (seed-averaged)

| Category | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|
| overall | -0.046 (-0.084, -0.011) significant | -0.046 (-0.084, -0.011) significant | -0.046 (-0.084, -0.011) significant |
| multi_hop | -0.067 (-0.106, -0.035) significant | -0.067 (-0.106, -0.035) significant | -0.067 (-0.106, -0.035) significant |
| distractor_heavy | -0.087 (-0.162, -0.026) significant | -0.087 (-0.162, -0.026) significant | -0.087 (-0.162, -0.026) significant |
| long_context | -0.094 (-0.216, -0.001) significant | -0.094 (-0.216, -0.001) significant | -0.094 (-0.216, -0.001) significant |
| no_answer | -0.050 (-0.100, +0.000) **NOT SIGNIFICANT** | -0.050 (-0.100, +0.000) **NOT SIGNIFICANT** | -0.050 (-0.100, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.073 (-0.083, +0.268) **NOT SIGNIFICANT** | +0.073 (-0.083, +0.268) **NOT SIGNIFICANT** | +0.073 (-0.083, +0.268) **NOT SIGNIFICANT** |

## mrr

| Category | `dense` | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|---|
| overall | 0.129 (n=114) | 0.006 (n=114) | 0.006 (n=114) | 0.006 (n=114) |
| multi_hop | 0.132 (n=93) | 0.000 (n=93) | 0.000 (n=93) | 0.000 (n=93) |
| distractor_heavy | 0.121 (n=42) | 0.000 (n=42) | 0.000 (n=42) | 0.000 (n=42) |
| long_context | 0.110 (n=9) | 0.000 (n=9) | 0.000 (n=9) | 0.000 (n=9) |
| no_answer | 0.062 (n=2) | 0.000 (n=2) | 0.000 (n=2) | 0.000 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.179 (n=13) | 0.051 (n=13) | 0.051 (n=13) | 0.051 (n=13) |

### mrr — paired CI delta vs `dense` (seed-averaged)

| Category | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|
| overall | -0.123 (-0.177, -0.075) significant | -0.123 (-0.177, -0.075) significant | -0.123 (-0.177, -0.075) significant |
| multi_hop | -0.132 (-0.192, -0.082) significant | -0.132 (-0.192, -0.082) significant | -0.132 (-0.192, -0.082) significant |
| distractor_heavy | -0.121 (-0.202, -0.050) significant | -0.121 (-0.202, -0.050) significant | -0.121 (-0.202, -0.050) significant |
| long_context | -0.110 (-0.225, -0.023) significant | -0.110 (-0.225, -0.023) significant | -0.110 (-0.225, -0.023) significant |
| no_answer | -0.062 (-0.125, +0.000) **NOT SIGNIFICANT** | -0.062 (-0.125, +0.000) **NOT SIGNIFICANT** | -0.062 (-0.125, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.128 (-0.368, +0.051) **NOT SIGNIFICANT** | -0.128 (-0.368, +0.051) **NOT SIGNIFICANT** | -0.128 (-0.368, +0.051) **NOT SIGNIFICANT** |

## ndcg@10

| Category | `dense` | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|---|
| overall | 0.067 (n=114) | 0.009 (n=114) | 0.009 (n=114) | 0.009 (n=114) |
| multi_hop | 0.065 (n=93) | 0.000 (n=93) | 0.000 (n=93) | 0.000 (n=93) |
| distractor_heavy | 0.068 (n=42) | 0.000 (n=42) | 0.000 (n=42) | 0.000 (n=42) |
| long_context | 0.073 (n=9) | 0.000 (n=9) | 0.000 (n=9) | 0.000 (n=9) |
| no_answer | 0.035 (n=2) | 0.000 (n=2) | 0.000 (n=2) | 0.000 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.119 (n=13) | 0.080 (n=13) | 0.080 (n=13) | 0.080 (n=13) |

### ndcg@10 — paired CI delta vs `dense` (seed-averaged)

| Category | `hybrid_bm25_k30` | `hybrid_bm25_k60` | `hybrid_bm25_k100` |
|---|---|---|---|
| overall | -0.058 (-0.089, -0.030) significant | -0.058 (-0.089, -0.030) significant | -0.058 (-0.089, -0.030) significant |
| multi_hop | -0.065 (-0.095, -0.040) significant | -0.065 (-0.095, -0.040) significant | -0.065 (-0.095, -0.040) significant |
| distractor_heavy | -0.068 (-0.116, -0.028) significant | -0.068 (-0.116, -0.028) significant | -0.068 (-0.116, -0.028) significant |
| long_context | -0.073 (-0.152, -0.007) significant | -0.073 (-0.152, -0.007) significant | -0.073 (-0.152, -0.007) significant |
| no_answer | -0.035 (-0.069, +0.000) **NOT SIGNIFICANT** | -0.035 (-0.069, +0.000) **NOT SIGNIFICANT** | -0.035 (-0.069, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.039 (-0.200, +0.109) **NOT SIGNIFICANT** | -0.039 (-0.200, +0.109) **NOT SIGNIFICANT** | -0.039 (-0.200, +0.109) **NOT SIGNIFICANT** |

## Per-category winner

Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `dense` fully above 0. "NOT SIGNIFICANT" = no variant's CI clears 0 (absolute rule #5).

| Category | Winner | Mean recall@10 | Delta CI vs `dense` |
|---|---|---|---|
| overall | `NOT SIGNIFICANT` | — | — |
| multi_hop | `NOT SIGNIFICANT` | — | — |
| distractor_heavy | `NOT SIGNIFICANT` | — | — |
| long_context | `NOT SIGNIFICANT` | — | — |
| no_answer | `NOT SIGNIFICANT` | — | — |
| ambiguous_query | `NOT SIGNIFICANT` | — | — |
| uncategorized | `NOT SIGNIFICANT` | — | — |

## Notes

* Planner-bypass: full query as the only sub-query, identity expansion, no rerank, `metadata_first=False` — isolates retrieval-mode impact from expansion / rerank / metadata-filter effects.
* All 4 variants share `data/index/real100`; only `plan['retrieval_backend']` and `plan['rrf_k']` differ. BM25 lazy-builds on the first hybrid call via `rag_retrieval.get_or_build_bm25` and is cached on the index dict, so `hybrid_bm25_k30` pays the BM25 build cost once and `k60`/`k100` are cache hits.
* `chunk_recall@k` is None for cases without `expected_terms` / `expected_doc_ids` (e.g. abstention) — those are dropped pairwise to preserve case alignment between variants.
* Seeds drive only the bootstrap RNG; retrieval itself is deterministic for the same query+index+backend+rrf_k (dense + BM25 both).
* Category bucketing uses `hardcase_categories` (semantic difficulty tags). Multi-tag cases appear in multiple buckets, so per-category counts overlap and per-category paired CIs share cases.
* `dense` is the delta baseline because ADR 0010's accept rationale for `hybrid` framed the question as "is hybrid actually better than dense?". Deltas above 0 favor the hybrid variant; below 0 favor dense.
* m3 (FlagEmbedding 3-channel RRF) is **out of scope** for Phase 3 — it requires a separate index build (`build_m3_index`), so deferring to Phase 3.5 keeps Phase 3 measurement narrow (mode ↔ index decoupled).
* k=10 / k=200 are **out of scope** for Phase 3 — k∈{30,60,100} brackets ADR 0010's k=60 default without inflating the variant count. Tighter/looser k swings can be added in a follow-up if k=30 vs k=100 shows a clean gradient.
