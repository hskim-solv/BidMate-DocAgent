# Phase 3.5 retrieval-eval — m3 mode ablation (real100 n=221, semantic embeddings)

Run: `20260518-0938-phase35-m3` · commit `cf1b2927c8` · index_dir=`data/index/real100_m3` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## Variants

| Variant | Backend | RRF k | Docs | Chunks |
|---|---|---|---|---|
| `dense_m3` | dense | — | 100 | 898 |
| `hybrid_bm25_k60_m3` | hybrid | 60 | 100 | 898 |
| `m3` | m3 | — | 100 | 898 |

## Latency (ms)

| Variant | p50 | p95 | mean | n |
|---|---|---|---|---|
| `dense_m3` | 699.367 | 3530.893 | 1141.947 | 221 |
| `hybrid_bm25_k60_m3` | 853.435 | 7641.01 | 1909.416 | 221 |
| `m3` | 1459.492 | 8232.231 | 2541.512 | 221 |

## chunk_recall@5

| Category | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.395 (n=37) | 0.427 (n=37) | 0.343 (n=37) |
| multi_hop | 0.246 (n=24) | 0.287 (n=24) | 0.231 (n=24) |
| distractor_heavy | 0.376 (n=7) | 0.362 (n=7) | 0.262 (n=7) |
| long_context | 0.200 (n=2) | 0.283 (n=2) | 0.283 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.676 (n=12) | 0.693 (n=12) | 0.547 (n=12) |

### chunk_recall@5 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.032 (-0.045, +0.099) **NOT SIGNIFICANT** | -0.052 (-0.145, +0.021) **NOT SIGNIFICANT** |
| multi_hop | +0.040 (-0.081, +0.139) **NOT SIGNIFICANT** | -0.016 (-0.119, +0.054) **NOT SIGNIFICANT** |
| distractor_heavy | -0.014 (-0.390, +0.262) **NOT SIGNIFICANT** | -0.114 (-0.429, +0.067) **NOT SIGNIFICANT** |
| long_context | +0.083 (+0.000, +0.167) **NOT SIGNIFICANT** | +0.083 (+0.000, +0.167) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.017 (+0.000, +0.050) **NOT SIGNIFICANT** | -0.129 (-0.328, +0.017) **NOT SIGNIFICANT** |

## chunk_recall@10

| Category | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.503 (n=37) | 0.534 (n=37) | 0.514 (n=37) |
| multi_hop | 0.351 (n=24) | 0.375 (n=24) | 0.373 (n=24) |
| distractor_heavy | 0.652 (n=7) | 0.638 (n=7) | 0.581 (n=7) |
| long_context | 0.483 (n=2) | 0.383 (n=2) | 0.483 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.767 (n=12) | 0.812 (n=12) | 0.772 (n=12) |

### chunk_recall@10 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.031 (-0.064, +0.122) **NOT SIGNIFICANT** | +0.011 (-0.068, +0.076) **NOT SIGNIFICANT** |
| multi_hop | +0.024 (-0.107, +0.145) **NOT SIGNIFICANT** | +0.022 (-0.092, +0.114) **NOT SIGNIFICANT** |
| distractor_heavy | -0.014 (-0.390, +0.262) **NOT SIGNIFICANT** | -0.071 (-0.429, +0.210) **NOT SIGNIFICANT** |
| long_context | -0.100 (-0.200, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.046 (-0.069, +0.205) **NOT SIGNIFICANT** | +0.006 (-0.062, +0.095) **NOT SIGNIFICANT** |

## mrr

| Category | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.443 (n=37) | 0.550 (n=37) | 0.521 (n=37) |
| multi_hop | 0.301 (n=24) | 0.457 (n=24) | 0.417 (n=24) |
| distractor_heavy | 0.270 (n=7) | 0.436 (n=7) | 0.402 (n=7) |
| long_context | 0.583 (n=2) | 1.000 (n=2) | 1.000 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.722 (n=12) | 0.699 (n=12) | 0.690 (n=12) |

### mrr — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.107 (+0.033, +0.190) significant | +0.078 (-0.012, +0.169) **NOT SIGNIFICANT** |
| multi_hop | +0.156 (+0.057, +0.263) significant | +0.116 (+0.019, +0.222) significant |
| distractor_heavy | +0.165 (-0.037, +0.391) **NOT SIGNIFICANT** | +0.131 (-0.080, +0.367) **NOT SIGNIFICANT** |
| long_context | +0.417 (+0.000, +0.833) **NOT SIGNIFICANT** | +0.417 (+0.000, +0.833) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | N/A | N/A |
| uncategorized | -0.023 (-0.053, +0.000) **NOT SIGNIFICANT** | -0.032 (-0.213, +0.119) **NOT SIGNIFICANT** |

## ndcg@10

| Category | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.412 (n=37) | 0.477 (n=37) | 0.429 (n=37) |
| multi_hop | 0.256 (n=24) | 0.339 (n=24) | 0.310 (n=24) |
| distractor_heavy | 0.361 (n=7) | 0.423 (n=7) | 0.374 (n=7) |
| long_context | 0.435 (n=2) | 0.484 (n=2) | 0.516 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.696 (n=12) | 0.720 (n=12) | 0.641 (n=12) |

### ndcg@10 — paired CI delta vs `dense_m3` (seed-averaged)

| Category | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.065 (-0.005, +0.138) **NOT SIGNIFICANT** | +0.017 (-0.048, +0.076) **NOT SIGNIFICANT** |
| multi_hop | +0.083 (-0.012, +0.182) **NOT SIGNIFICANT** | +0.054 (-0.012, +0.117) **NOT SIGNIFICANT** |
| distractor_heavy | +0.062 (-0.163, +0.260) **NOT SIGNIFICANT** | +0.013 (-0.144, +0.166) **NOT SIGNIFICANT** |
| long_context | +0.049 (-0.096, +0.195) **NOT SIGNIFICANT** | +0.081 (-0.033, +0.195) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.024 (-0.044, +0.122) **NOT SIGNIFICANT** | -0.056 (-0.193, +0.064) **NOT SIGNIFICANT** |

## Per-category winner

Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `dense_m3` fully above 0. "NOT SIGNIFICANT" = no variant's CI clears 0 (absolute rule #5).

| Category | Winner | Mean recall@10 | Delta CI vs `dense_m3` |
|---|---|---|---|
| overall | `NOT SIGNIFICANT` | — | — |
| multi_hop | `NOT SIGNIFICANT` | — | — |
| distractor_heavy | `NOT SIGNIFICANT` | — | — |
| long_context | `NOT SIGNIFICANT` | — | — |
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
