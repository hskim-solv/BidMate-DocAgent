# Phase 2 retrieval-eval — chunking ablation (real100 n=221)

Run: `20260517-2250-phase2-chunking` · commit `af461b1a90` · index_dir_current=`/Users/hskim/Desktop/projects/BidMate-DocAgent/data/index/real100` · eval_config=`/Users/hskim/Desktop/projects/BidMate-DocAgent/eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

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
| single_hop | 0.051 (n=112) | 0.057 (n=112) | 0.052 (n=112) | 0.041 (n=112) |
| multi_hop | 0.034 (n=1) | 0.018 (n=1) | 0.014 (n=1) | 0.033 (n=1) |
| no_answer | 0.500 (n=1) | 1.000 (n=1) | 0.000 (n=1) | 0.000 (n=1) |
| other | — | — | — | — |

### chunk_recall@5 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.010 (-0.008, +0.034) **NOT SIGNIFICANT** | -0.004 (-0.033, +0.024) **NOT SIGNIFICANT** | -0.014 (-0.031, +0.000) **NOT SIGNIFICANT** |
| single_hop | +0.006 (-0.010, +0.028) **NOT SIGNIFICANT** | +0.001 (-0.028, +0.027) **NOT SIGNIFICANT** | -0.010 (-0.025, +0.003) **NOT SIGNIFICANT** |
| multi_hop | -0.016 (-0.016, -0.016) significant | -0.020 (-0.020, -0.020) significant | -0.001 (-0.001, -0.001) significant |
| no_answer | +0.500 (+0.500, +0.500) significant | -0.500 (-0.500, -0.500) significant | -0.500 (-0.500, -0.500) significant |
| other | N/A | N/A | N/A |

## chunk_recall@10

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.064 (n=114) | 0.078 (n=114) | 0.081 (n=114) | 0.061 (n=114) |
| single_hop | 0.060 (n=112) | 0.070 (n=112) | 0.082 (n=112) | 0.053 (n=112) |
| multi_hop | 0.057 (n=1) | 0.027 (n=1) | 0.014 (n=1) | 0.054 (n=1) |
| no_answer | 0.500 (n=1) | 1.000 (n=1) | 0.000 (n=1) | 1.000 (n=1) |
| other | — | — | — | — |

### chunk_recall@10 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.014 (-0.007, +0.040) **NOT SIGNIFICANT** | +0.017 (-0.011, +0.050) **NOT SIGNIFICANT** | -0.003 (-0.022, +0.017) **NOT SIGNIFICANT** |
| single_hop | +0.010 (-0.011, +0.035) **NOT SIGNIFICANT** | +0.022 (-0.006, +0.055) **NOT SIGNIFICANT** | -0.007 (-0.027, +0.012) **NOT SIGNIFICANT** |
| multi_hop | -0.030 (-0.030, -0.030) significant | -0.043 (-0.043, -0.043) significant | -0.002 (-0.002, -0.002) significant |
| no_answer | +0.500 (+0.500, +0.500) significant | -0.500 (-0.500, -0.500) significant | +0.500 (+0.500, +0.500) significant |
| other | N/A | N/A | N/A |

## mrr

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.129 (n=114) | 0.198 (n=114) | 0.103 (n=114) | 0.102 (n=114) |
| single_hop | 0.118 (n=112) | 0.195 (n=112) | 0.096 (n=112) | 0.100 (n=112) |
| multi_hop | 1.000 (n=1) | 0.250 (n=1) | 1.000 (n=1) | 0.333 (n=1) |
| no_answer | 0.500 (n=1) | 0.500 (n=1) | 0.000 (n=1) | 0.167 (n=1) |
| other | — | — | — | — |

### mrr — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.070 (+0.020, +0.122) significant | -0.025 (-0.059, +0.002) **NOT SIGNIFICANT** | -0.026 (-0.070, +0.015) **NOT SIGNIFICANT** |
| single_hop | +0.078 (+0.028, +0.130) significant | -0.021 (-0.055, +0.006) **NOT SIGNIFICANT** | -0.018 (-0.059, +0.024) **NOT SIGNIFICANT** |
| multi_hop | -0.750 (-0.750, -0.750) significant | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.667 (-0.667, -0.667) significant |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.500 (-0.500, -0.500) significant | -0.333 (-0.333, -0.333) significant |
| other | N/A | N/A | N/A |

## ndcg@10

| Category | `current` | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|---|
| overall | 0.067 (n=114) | 0.092 (n=114) | 0.060 (n=114) | 0.054 (n=114) |
| single_hop | 0.059 (n=112) | 0.085 (n=112) | 0.059 (n=112) | 0.048 (n=112) |
| multi_hop | 0.602 (n=1) | 0.258 (n=1) | 0.220 (n=1) | 0.442 (n=1) |
| no_answer | 0.387 (n=1) | 0.631 (n=1) | 0.000 (n=1) | 0.412 (n=1) |
| other | — | — | — | — |

### ndcg@10 — paired CI delta vs `current` (seed-averaged)

| Category | `smaller` | `larger` | `structure_aware` |
|---|---|---|---|
| overall | +0.025 (+0.001, +0.051) significant | -0.007 (-0.026, +0.012) **NOT SIGNIFICANT** | -0.013 (-0.030, +0.004) **NOT SIGNIFICANT** |
| single_hop | +0.026 (+0.003, +0.052) significant | -0.000 (-0.018, +0.017) **NOT SIGNIFICANT** | -0.012 (-0.030, +0.006) **NOT SIGNIFICANT** |
| multi_hop | -0.343 (-0.343, -0.343) significant | -0.381 (-0.381, -0.381) significant | -0.160 (-0.160, -0.160) significant |
| no_answer | +0.244 (+0.244, +0.244) significant | -0.387 (-0.387, -0.387) significant | +0.025 (+0.025, +0.025) significant |
| other | N/A | N/A | N/A |

## Per-category winner

Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `current` fully above 0. "NOT SIGNIFICANT" = no variant's CI clears 0 (absolute rule #5).

| Category | Winner | Mean recall@10 | Delta CI vs current |
|---|---|---|---|
| overall | `NOT SIGNIFICANT` | — | — |
| single_hop | `NOT SIGNIFICANT` | — | — |
| multi_hop | `NOT SIGNIFICANT` | — | — |
| no_answer | `smaller` | 1.000 | +0.500 (+0.500, +0.500) significant |
| other | `NOT SIGNIFICANT` | — | — |

## Notes

* Planner-bypass: full query as the only sub-query, identity expansion, no rerank — isolates chunking impact from query expansion / rerank effects.
* `chunk_recall@k` is None for cases without `expected_terms` / `expected_doc_ids` (e.g. abstention) — those are dropped pairwise to preserve case alignment between current and the variant.
* Seeds drive only the bootstrap RNG; retrieval itself is deterministic for the same query+index (hashing-backend / dense backend both).
* Index storage: `data/index/phase2_smaller`, `phase2_larger`, `phase2_structure_aware`.
