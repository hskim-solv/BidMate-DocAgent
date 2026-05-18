# Phase 3.5 retrieval-eval — m3 mode ablation (real100 n=221, semantic embeddings)

Run: `20260518-2156-phase35-m3` · commit `f4e30cd544` · index_dir=`data/index/real100_m3` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## Variants

| Variant | Backend | RRF k | Docs | Chunks |
|---|---|---|---|---|
| `dense_m3` | dense | — | 100 | 26376 |
| `hybrid_bm25_k60_m3` | hybrid | 60 | 100 | 26376 |

## Latency (ms)

| Variant | p50 | p95 | mean | n |
|---|---|---|---|---|
| `dense_m3` | 558.865 | 2220.352 | 847.273 | 221 |
| `hybrid_bm25_k60_m3` | 757.248 | 1236.946 | 801.259 | 221 |

## chunk_recall@5

| Category | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.248 (n=114) | 0.296 (n=114) |
| multi_hop | 0.196 (n=93) | 0.248 (n=93) |
| distractor_heavy | 0.242 (n=42) | 0.304 (n=42) |
| long_context | 0.293 (n=9) | 0.354 (n=9) |
| no_answer | 0.600 (n=2) | 0.600 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.530 (n=13) | 0.538 (n=13) |

### chunk_recall@5 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.048 (+0.013, +0.088) significant |
| multi_hop | +0.052 (+0.021, +0.092) significant |
| distractor_heavy | +0.062 (+0.003, +0.138) significant |
| long_context | +0.060 (+0.000, +0.172) significant |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.008 (-0.171, +0.219) **NOT SIGNIFICANT** |

## chunk_recall@10

| Category | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.288 (n=114) | 0.340 (n=114) |
| multi_hop | 0.240 (n=93) | 0.283 (n=93) |
| distractor_heavy | 0.287 (n=42) | 0.354 (n=42) |
| long_context | 0.301 (n=9) | 0.434 (n=9) |
| no_answer | 0.600 (n=2) | 0.600 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.559 (n=13) | 0.620 (n=13) |

### chunk_recall@10 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.052 (+0.020, +0.088) significant |
| multi_hop | +0.043 (+0.018, +0.073) significant |
| distractor_heavy | +0.067 (+0.015, +0.131) significant |
| long_context | +0.133 (+0.017, +0.278) significant |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.060 (-0.110, +0.256) **NOT SIGNIFICANT** |

## mrr

| Category | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.515 (n=114) | 0.625 (n=114) |
| multi_hop | 0.501 (n=93) | 0.631 (n=93) |
| distractor_heavy | 0.499 (n=42) | 0.581 (n=42) |
| long_context | 0.619 (n=9) | 0.701 (n=9) |
| no_answer | 0.750 (n=2) | 0.750 (n=2) |
| ambiguous_query | 1.000 (n=1) | 0.500 (n=1) |
| uncategorized | 0.579 (n=13) | 0.596 (n=13) |

### mrr — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.110 (+0.056, +0.165) significant |
| multi_hop | +0.130 (+0.073, +0.192) significant |
| distractor_heavy | +0.082 (+0.016, +0.159) significant |
| long_context | +0.082 (+0.011, +0.183) significant |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | -0.500 (-0.500, -0.500) significant |
| uncategorized | +0.018 (-0.191, +0.215) **NOT SIGNIFICANT** |

## ndcg@10

| Category | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.318 (n=114) | 0.383 (n=114) |
| multi_hop | 0.277 (n=93) | 0.347 (n=93) |
| distractor_heavy | 0.309 (n=42) | 0.372 (n=42) |
| long_context | 0.417 (n=9) | 0.534 (n=9) |
| no_answer | 0.473 (n=2) | 0.468 (n=2) |
| ambiguous_query | 1.000 (n=1) | 0.631 (n=1) |
| uncategorized | 0.544 (n=13) | 0.573 (n=13) |

### ndcg@10 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.065 (+0.032, +0.099) significant |
| multi_hop | +0.070 (+0.040, +0.106) significant |
| distractor_heavy | +0.063 (+0.007, +0.126) significant |
| long_context | +0.117 (+0.032, +0.223) significant |
| no_answer | -0.005 (-0.010, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | -0.369 (-0.369, -0.369) significant |
| uncategorized | +0.029 (-0.140, +0.189) **NOT SIGNIFICANT** |

## Per-category winner

Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `dense_m3` fully above 0. "NOT SIGNIFICANT" = no variant's CI clears 0 (absolute rule #5).

| Category | Winner | Mean recall@10 | Delta CI vs `dense_m3` |
|---|---|---|---|
| overall | `hybrid_bm25_k60_m3` | 0.340 | +0.052 (+0.020, +0.088) significant |
| multi_hop | `hybrid_bm25_k60_m3` | 0.283 | +0.043 (+0.018, +0.073) significant |
| distractor_heavy | `hybrid_bm25_k60_m3` | 0.354 | +0.067 (+0.015, +0.131) significant |
| long_context | `hybrid_bm25_k60_m3` | 0.434 | +0.133 (+0.017, +0.278) significant |
| no_answer | `NOT SIGNIFICANT` | — | — |
| ambiguous_query | `NOT SIGNIFICANT` | — | — |
| uncategorized | `NOT SIGNIFICANT` | — | — |

## Notes

* Planner-bypass: full query as the only sub-query, identity expansion, no rerank, `metadata_first=False` — isolates retrieval-mode impact from expansion / rerank / metadata-filter effects (same discipline as Phase 3).
* All 3 variants share `data/index/real100_m3` (BGE-M3 1024-dim dense). `hybrid_bm25_k60_m3` uses BM25 lazy-built on the index dict; `m3` populates `index['_m3_cache']` (sparse + colbert per chunk, in-memory only per ADR 0025 spike-mode, no disk persist) on its first call. `--warmup` absorbs the ~2 min cache cold-start so per-case latency reflects cache-hit cost.
* m3's RRF dense channel reuses the index's existing dense channel (`rag_retrieval.py:449-454`) — for this run it IS the BGE-M3 dense (the index was built with `--model BAAI/bge-m3`), so the 3 channels are all BGE-M3 (dense + sparse + colbert). On hashing-built indexes the dense channel would be hashing, mixing embedding families.
* `chunk_recall@k` is None for cases without `expected_terms` / `expected_doc_ids` (e.g. abstention) — those are dropped pairwise to preserve case alignment between variants.
* Seeds drive only the bootstrap RNG; retrieval itself is deterministic for the same query+index+backend+rrf_k (dense + BM25 + m3 sparse/colbert).
* Category bucketing uses `hardcase_categories` (semantic difficulty tags). Multi-tag cases appear in multiple buckets, so per-category counts overlap and per-category paired CIs share cases.
* `dense_m3` is the delta baseline because Phase 3.5 isolates **multi-channel vs single-channel under semantic embeddings**. Deltas above 0 favor the multi-channel variant (hybrid or m3); below 0 favor dense alone.
* **Phase 3 cross-ref + runner bug retraction**: `reports/retrieval/phase3_mode_20260518T032404Z/` reported all 3 `hybrid_bm25_k{30,60,100}` variants byte-identical and attributed it to BM25 channel dominance. **That conclusion was wrong**: the Phase 3 runner called `retrieve_candidates` (candidate generation only) without the second-stage `apply_fusion_and_reranking` (RRF fusion + final top-k). For hybrid + m3 backends `retrieve_candidates` returns `score=0.0` placeholders, so the per-case ranking collapsed to chunk_id insertion order — making every k value byte-identical. Phase 3.5 fixes the wire-up (both calls in `run_single_case`); the hashing-index re-run is a follow-up. Cross-backend delta math (hashing `dense` vs `dense_m3`) remains confounded by the embedding family swap and is NOT computed.
* **Chunk count caveat**: the BGE-M3 index used the `data_list_csv_text` loader for both HWP and PDF (per ADR 0049 graceful fallback), yielding ~9 chunks/doc vs real100's ~264 chunks/doc with `kordoc` full extraction. Re-embedding 26k kordoc chunks with BGE-M3 on MPS would take >2h (per-batch GPU dispatch overhead); the csv_text fallback keeps the build under 20 min while preserving the within-Phase-3.5 paired CI claim. Absolute `chunk_recall@k` on this index is NOT directly comparable to Phase 3's kordoc-built numbers — only Phase 3.5 internal deltas are.
* **Runner-side m3 batching (measurement-only optimization)**: per-query colbert max-sim is the dominant cost on this index (per-chunk Python-loop matmul × ~900 chunks × ~50s/query observed on the unoptimized path). The runner concatenates all chunk colbert vectors into one `(Σ T_d, 1024)` matrix and does **one** matmul per unique query, then splits the columns back per chunk for the row-wise max+sum. Mathematically identical to the per-chunk path (each chunk's column slice is independent), but ~100× faster. The patch lives in the runner (`_prime_m3_index_cache_and_colbert`); `rag_m3.py` / `rag_retrieval.py` unchanged.
* **Out of scope**: per-channel m3 ablation (sparse-only, colbert-only — see ADR 0010 'Alternatives considered'); RRF-k sweep on hybrid_bm25 (Phase 3 already showed k=30/60/100 byte-identical on hashing); cross-encoder rerank stacked on top (Phase 4).
* ADR cross-refs: ADR 0010 (BGE-M3 multi-channel deferred), ADR 0021 (m3_full analysis row), ADR 0032 (torch>=2.6 unblock — closes the install blocker that originally deferred this measurement).
