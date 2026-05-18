# Phase 2 retrieval-eval — chunking ablation (real100 n=221)

Run: `20260518-0202-phase2-chunking-reaggregate` · commit `af461b1a90` · index_dir_current=`/Users/hskim/Desktop/projects/BidMate-DocAgent/data/index/real100` · eval_config=`/Users/hskim/Desktop/projects/BidMate-DocAgent/eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## Variants

| Variant | Strategy | Max chars | Overlap | Docs | Chunks | Section detect | Heuristic engaged |
|---|---|---|---|---|---|---|---|
| `current` | fixed | 520 | 1 | 100 | 26376 | 0.0% | — |
| `smaller` | fixed | 260 | 1 | 100 | 55281 | 0.0% | — |
| `larger` | fixed | 1040 | 1 | 100 | 12843 | 0.0% | — |
| `structure_aware` | section | 520 | 1 | 100 | 30937 | 100.0% | 100.0% |

## Latency (ms)

| Variant | p50 | p95 | mean | n |
|---|---|---|---|---|
| `current` | 389.616 | 588.575 | 431.721 | 221 |
| `smaller` | 764.095 | 863.732 | 710.538 | 221 |
| `larger` | 324.013 | 480.125 | 347.048 | 221 |
| `structure_aware` | 488.694 | 722.818 | 543.176 | 221 |

## chunk_recall@5

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.055 (n=114) | 0.065 (n=114) | 0.051 (n=114) | 0.041 (n=114) |
| multi_hop | 0.056 (n=93) | 0.068 (n=93) | 0.050 (n=93) | 0.049 (n=93) |
| distractor_heavy | 0.083 (n=42) | 0.117 (n=42) | 0.070 (n=42) | 0.063 (n=42) |
| long_context | 0.038 (n=9) | 0.022 (n=9) | 0.000 (n=9) | 0.037 (n=9) |
| no_answer | 0.000 (n=2) | 0.045 (n=2) | 0.125 (n=2) | 0.111 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.080 (n=13) | 0.065 (n=13) | 0.091 (n=13) | 0.003 (n=13) |

### chunk_recall@5 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.010 (-0.008, +0.034) **NOT SIGNIFICANT** | -0.004 (-0.033, +0.024) **NOT SIGNIFICANT** | -0.014 (-0.031, +0.000) **NOT SIGNIFICANT** |
| multi_hop | +0.012 (-0.010, +0.041) **NOT SIGNIFICANT** | -0.006 (-0.040, +0.029) **NOT SIGNIFICANT** | -0.006 (-0.021, +0.005) **NOT SIGNIFICANT** |
| distractor_heavy | +0.035 (-0.008, +0.098) **NOT SIGNIFICANT** | -0.012 (-0.086, +0.057) **NOT SIGNIFICANT** | -0.020 (-0.048, -0.000) significant |
| long_context | -0.016 (-0.056, +0.007) **NOT SIGNIFICANT** | -0.038 (-0.113, +0.000) **NOT SIGNIFICANT** | -0.001 (-0.004, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.045 (+0.000, +0.091) **NOT SIGNIFICANT** | +0.125 (+0.000, +0.250) **NOT SIGNIFICANT** | +0.111 (+0.000, +0.222) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.014 (-0.040, +0.000) **NOT SIGNIFICANT** | +0.011 (-0.005, +0.038) **NOT SIGNIFICANT** | -0.077 (-0.192, +0.000) **NOT SIGNIFICANT** |

## chunk_recall@10

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.064 (n=114) | 0.078 (n=114) | 0.081 (n=114) | 0.061 (n=114) |
| multi_hop | 0.067 (n=93) | 0.083 (n=93) | 0.086 (n=93) | 0.074 (n=93) |
| distractor_heavy | 0.087 (n=42) | 0.129 (n=42) | 0.122 (n=42) | 0.096 (n=42) |
| long_context | 0.094 (n=9) | 0.022 (n=9) | 0.002 (n=9) | 0.037 (n=9) |
| no_answer | 0.050 (n=2) | 0.091 (n=2) | 0.188 (n=2) | 0.222 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.081 (n=13) | 0.066 (n=13) | 0.093 (n=13) | 0.004 (n=13) |

### chunk_recall@10 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.014 (-0.007, +0.040) **NOT SIGNIFICANT** | +0.017 (-0.011, +0.050) **NOT SIGNIFICANT** | -0.003 (-0.022, +0.017) **NOT SIGNIFICANT** |
| multi_hop | +0.016 (-0.010, +0.048) **NOT SIGNIFICANT** | +0.019 (-0.015, +0.060) **NOT SIGNIFICANT** | +0.007 (-0.012, +0.028) **NOT SIGNIFICANT** |
| distractor_heavy | +0.042 (-0.001, +0.104) **NOT SIGNIFICANT** | +0.035 (-0.024, +0.113) **NOT SIGNIFICANT** | +0.009 (-0.012, +0.038) **NOT SIGNIFICANT** |
| long_context | -0.072 (-0.184, +0.005) **NOT SIGNIFICANT** | -0.092 (-0.216, +0.001) **NOT SIGNIFICANT** | -0.057 (-0.168, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.041 (+0.000, +0.082) **NOT SIGNIFICANT** | +0.138 (+0.000, +0.275) **NOT SIGNIFICANT** | +0.172 (+0.000, +0.344) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.015 (-0.042, +0.000) **NOT SIGNIFICANT** | +0.011 (-0.007, +0.040) **NOT SIGNIFICANT** | -0.077 (-0.192, +0.000) **NOT SIGNIFICANT** |

## mrr

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.129 (n=114) | 0.198 (n=114) | 0.103 (n=114) | 0.102 (n=114) |
| multi_hop | 0.132 (n=93) | 0.207 (n=93) | 0.099 (n=93) | 0.120 (n=93) |
| distractor_heavy | 0.121 (n=42) | 0.186 (n=42) | 0.089 (n=42) | 0.075 (n=42) |
| long_context | 0.110 (n=9) | 0.199 (n=9) | 0.012 (n=9) | 0.062 (n=9) |
| no_answer | 0.062 (n=2) | 0.500 (n=2) | 0.125 (n=2) | 0.531 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.179 (n=13) | 0.173 (n=13) | 0.192 (n=13) | 0.035 (n=13) |

### mrr — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.070 (+0.020, +0.122) significant | -0.025 (-0.059, +0.002) **NOT SIGNIFICANT** | -0.026 (-0.070, +0.015) **NOT SIGNIFICANT** |
| multi_hop | +0.075 (+0.021, +0.134) significant | -0.032 (-0.072, +0.003) **NOT SIGNIFICANT** | -0.012 (-0.056, +0.032) **NOT SIGNIFICANT** |
| distractor_heavy | +0.065 (-0.003, +0.150) **NOT SIGNIFICANT** | -0.031 (-0.092, +0.013) **NOT SIGNIFICANT** | -0.046 (-0.095, -0.007) significant |
| long_context | +0.089 (-0.038, +0.231) **NOT SIGNIFICANT** | -0.098 (-0.211, -0.017) significant | -0.048 (-0.112, +0.006) **NOT SIGNIFICANT** |
| no_answer | +0.438 (+0.000, +0.875) **NOT SIGNIFICANT** | +0.062 (+0.000, +0.125) **NOT SIGNIFICANT** | +0.469 (+0.062, +0.875) significant |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.006 (-0.173, +0.154) **NOT SIGNIFICANT** | +0.013 (+0.000, +0.038) **NOT SIGNIFICANT** | -0.144 (-0.333, +0.001) **NOT SIGNIFICANT** |

## ndcg@10

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.067 (n=114) | 0.092 (n=114) | 0.060 (n=114) | 0.054 (n=114) |
| multi_hop | 0.065 (n=93) | 0.093 (n=93) | 0.060 (n=93) | 0.062 (n=93) |
| distractor_heavy | 0.068 (n=42) | 0.116 (n=42) | 0.066 (n=42) | 0.056 (n=42) |
| long_context | 0.073 (n=9) | 0.059 (n=9) | 0.007 (n=9) | 0.038 (n=9) |
| no_answer | 0.035 (n=2) | 0.142 (n=2) | 0.141 (n=2) | 0.244 (n=2) |
| ambiguous_query | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| uncategorized | 0.119 (n=13) | 0.103 (n=13) | 0.098 (n=13) | 0.034 (n=13) |

### ndcg@10 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.025 (+0.001, +0.051) significant | -0.007 (-0.026, +0.012) **NOT SIGNIFICANT** | -0.013 (-0.030, +0.004) **NOT SIGNIFICANT** |
| multi_hop | +0.028 (+0.002, +0.059) significant | -0.006 (-0.028, +0.017) **NOT SIGNIFICANT** | -0.003 (-0.018, +0.012) **NOT SIGNIFICANT** |
| distractor_heavy | +0.048 (+0.000, +0.112) significant | -0.002 (-0.039, +0.034) **NOT SIGNIFICANT** | -0.012 (-0.029, +0.001) **NOT SIGNIFICANT** |
| long_context | -0.014 (-0.074, +0.037) **NOT SIGNIFICANT** | -0.065 (-0.147, -0.002) significant | -0.035 (-0.083, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.107 (+0.000, +0.214) **NOT SIGNIFICANT** | +0.107 (+0.000, +0.214) **NOT SIGNIFICANT** | +0.209 (+0.000, +0.419) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | -0.016 (-0.092, +0.054) **NOT SIGNIFICANT** | -0.021 (-0.084, +0.019) **NOT SIGNIFICANT** | -0.085 (-0.195, +0.000) **NOT SIGNIFICANT** |

## Per-category winner

Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `current` fully above 0. "NOT SIGNIFICANT" = no variant's CI clears 0 (absolute rule #5).

| Category | Winner | Mean recall@10 | Delta CI vs current |
|---|---|---|---|
| overall | `NOT SIGNIFICANT` | — | — |
| multi_hop | `NOT SIGNIFICANT` | — | — |
| distractor_heavy | `NOT SIGNIFICANT` | — | — |
| long_context | `NOT SIGNIFICANT` | — | — |
| no_answer | `NOT SIGNIFICANT` | — | — |
| ambiguous_query | `NOT SIGNIFICANT` | — | — |
| uncategorized | `NOT SIGNIFICANT` | — | — |

## Notes

* Planner-bypass: full query as the only sub-query, identity expansion, no rerank — isolates chunking impact from query expansion / rerank effects.
* `chunk_recall@k` is None for cases without `expected_terms` / `expected_doc_ids` (e.g. abstention) — those are dropped pairwise to preserve case alignment between current and the variant.
* Seeds drive only the bootstrap RNG; retrieval itself is deterministic for the same query+index (hashing-backend / dense backend both).
* Index storage: `data/index/phase2_smaller`, `phase2_larger`, `phase2_structure_aware`.
* Category bucketing uses `hardcase_categories` (semantic difficulty tags) from the eval config. The legacy `query_type` field (single_doc / multi_doc / follow_up / abstention) is **not** used here. A case tagged with N categories appears in N buckets, so per-category counts overlap and per-category paired CIs share cases — combining multiple categories via OR inflates family-wise error rate.
* `uncategorized` covers cases without `hardcase_categories` tags (typically the initial seed + probe cases authored before the tag schema). They still contribute to `overall`.
* Phase 1 baseline (`UNIFIED_PHASE1_REPORT.md`) categorized by `query_type` (e.g. `multi_doc → multi_hop` with n=1); direct cross-phase category-by-category trend comparison is not meaningful until Phase 1 is re-aggregated against the same `hardcase_categories` field.
* This report was regenerated via `--reaggregate` from `reports/retrieval/phase2_chunking_20260518-0740/raw_results.json` — categorization re-derived from `hardcase_categories`; retrieval scores in `raw_results.json` are unchanged byte-for-byte modulo the injected `categories` field.
