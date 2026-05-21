# Phase 3.5 retrieval-eval — m3 검색 모드(mode) ablation (real100 n=221, 의미 임베딩(semantic embeddings))

Run: `20260521-0334-phase35-m3-reaggregate` · commit `5e5f07bc96` · index_dir=`data/index/real100_m3` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## 변형(variants)

| 변형 | backend | RRF k | 문서 | 청크 |
|---|---|---|---|---|
| `dense_m3` | dense | — | 100 | 898 |
| `hybrid_bm25_k60_m3` | hybrid | 60 | 100 | 898 |
| `m3` | m3 | — | 100 | 898 |

## 지연시간(latency, ms)

| 변형 | p50 | p95 | mean | n |
|---|---|---|---|---|
| `dense_m3` | 699.367 | 3530.893 | 1141.947 | 221 |
| `hybrid_bm25_k60_m3` | 853.435 | 7641.01 | 1909.416 | 221 |
| `m3` | 1459.492 | 8232.231 | 2541.512 | 221 |

## chunk_recall@5

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.395 (n=37) | 0.427 (n=37) | 0.343 (n=37) |
| multi_hop | 0.246 (n=24) | 0.287 (n=24) | 0.231 (n=24) |
| distractor_heavy | 0.376 (n=7) | 0.362 (n=7) | 0.262 (n=7) |
| long_context | 0.200 (n=2) | 0.283 (n=2) | 0.283 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.676 (n=12) | 0.693 (n=12) | 0.547 (n=12) |

### chunk_recall@5 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.032 (-0.045, +0.099) **유의하지 않음** | -0.052 (-0.145, +0.021) **유의하지 않음** |
| multi_hop | +0.040 (-0.081, +0.139) **유의하지 않음** | -0.016 (-0.119, +0.054) **유의하지 않음** |
| distractor_heavy | -0.014 (-0.390, +0.262) **유의하지 않음** | -0.114 (-0.429, +0.067) **유의하지 않음** |
| long_context | +0.083 (+0.000, +0.167) **유의하지 않음** | +0.083 (+0.000, +0.167) **유의하지 않음** |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.017 (+0.000, +0.050) **유의하지 않음** | -0.129 (-0.328, +0.017) **유의하지 않음** |

## chunk_recall@10

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.503 (n=37) | 0.534 (n=37) | 0.514 (n=37) |
| multi_hop | 0.351 (n=24) | 0.375 (n=24) | 0.373 (n=24) |
| distractor_heavy | 0.652 (n=7) | 0.638 (n=7) | 0.581 (n=7) |
| long_context | 0.483 (n=2) | 0.383 (n=2) | 0.483 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.767 (n=12) | 0.812 (n=12) | 0.772 (n=12) |

### chunk_recall@10 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.031 (-0.064, +0.122) **유의하지 않음** | +0.011 (-0.068, +0.076) **유의하지 않음** |
| multi_hop | +0.024 (-0.107, +0.145) **유의하지 않음** | +0.022 (-0.092, +0.114) **유의하지 않음** |
| distractor_heavy | -0.014 (-0.390, +0.262) **유의하지 않음** | -0.071 (-0.429, +0.210) **유의하지 않음** |
| long_context | -0.100 (-0.200, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.046 (-0.069, +0.205) **유의하지 않음** | +0.006 (-0.062, +0.095) **유의하지 않음** |

## mrr

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.443 (n=37) | 0.550 (n=37) | 0.521 (n=37) |
| multi_hop | 0.301 (n=24) | 0.457 (n=24) | 0.417 (n=24) |
| distractor_heavy | 0.270 (n=7) | 0.436 (n=7) | 0.402 (n=7) |
| long_context | 0.583 (n=2) | 1.000 (n=2) | 1.000 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.722 (n=12) | 0.699 (n=12) | 0.690 (n=12) |

### mrr — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.107 (+0.033, +0.190) 유의함 | +0.078 (-0.012, +0.169) **유의하지 않음** |
| multi_hop | +0.156 (+0.057, +0.263) 유의함 | +0.116 (+0.019, +0.222) 유의함 |
| distractor_heavy | +0.165 (-0.037, +0.391) **유의하지 않음** | +0.131 (-0.080, +0.367) **유의하지 않음** |
| long_context | +0.417 (+0.000, +0.833) **유의하지 않음** | +0.417 (+0.000, +0.833) **유의하지 않음** |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | N/A | N/A |
| uncategorized | -0.023 (-0.053, +0.000) **유의하지 않음** | -0.032 (-0.213, +0.119) **유의하지 않음** |

## ndcg@10

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|---|
| overall | 0.412 (n=37) | 0.477 (n=37) | 0.429 (n=37) |
| multi_hop | 0.256 (n=24) | 0.339 (n=24) | 0.310 (n=24) |
| distractor_heavy | 0.361 (n=7) | 0.423 (n=7) | 0.374 (n=7) |
| long_context | 0.435 (n=2) | 0.484 (n=2) | 0.516 (n=2) |
| no_answer | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| ambiguous_query | — | — | — |
| uncategorized | 0.696 (n=12) | 0.720 (n=12) | 0.641 (n=12) |

### ndcg@10 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` | `m3` |
|---|---|---|
| overall | +0.065 (-0.005, +0.138) **유의하지 않음** | +0.017 (-0.048, +0.076) **유의하지 않음** |
| multi_hop | +0.083 (-0.012, +0.182) **유의하지 않음** | +0.054 (-0.012, +0.117) **유의하지 않음** |
| distractor_heavy | +0.062 (-0.163, +0.260) **유의하지 않음** | +0.013 (-0.144, +0.166) **유의하지 않음** |
| long_context | +0.049 (-0.096, +0.195) **유의하지 않음** | +0.081 (-0.033, +0.195) **유의하지 않음** |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | N/A | N/A |
| uncategorized | +0.024 (-0.044, +0.122) **유의하지 않음** | -0.056 (-0.193, +0.064) **유의하지 않음** |

## 카테고리별 winner

winner = `chunk_recall@10` 평균이 가장 높으면서 `dense_m3` 대비 paired CI 가 완전히 0 위인 변형. "유의하지 않음" = 어떤 변형의 CI 도 0 을 넘지 못함 (절대 규칙 #5).

| 카테고리 | winner | 평균 recall@10 | `dense_m3` 대비 delta CI |
|---|---|---|---|
| overall | `유의하지 않음` | — | — |
| multi_hop | `유의하지 않음` | — | — |
| distractor_heavy | `유의하지 않음` | — | — |
| long_context | `유의하지 않음` | — | — |
| no_answer | `유의하지 않음` | — | — |
| ambiguous_query | `유의하지 않음` | — | — |
| uncategorized | `유의하지 않음` | — | — |

## 비고(notes)

* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, rerank 없음, `metadata_first=False` — 검색 모드 효과를 expansion / rerank / metadata-filter 효과로부터 격리한다 (Phase 3 과 동일 규율).
* 3 변형 모두 `data/index/real100_m3`(BGE-M3 1024-dim dense)를 공유한다. `hybrid_bm25_k60_m3` 는 index dict 에 lazy-build 된 BM25 를 쓰고; `m3` 는 첫 호출 시 `index['_m3_cache']`(청크별 sparse + colbert, ADR 0025 spike-mode 라 in-memory only, 디스크 미persist)를 채운다. `--warmup` 이 ~2 분 캐시 cold-start 를 흡수하므로 케이스별 지연시간은 캐시 hit 비용을 반영한다.
* m3 의 RRF dense 채널은 인덱스의 기존 dense 채널을 재사용한다(`rag_retrieval.py:449-454`) — 이 run 에서는 그것이 BGE-M3 dense 다(인덱스가 `--model BAAI/bge-m3` 로 빌드됨), 따라서 3 채널 모두 BGE-M3(dense + sparse + colbert)다. hashing 으로 빌드된 인덱스에서는 dense 채널이 hashing 이라 임베딩 패밀리가 섞이게 된다.
* `chunk_recall@k` 는 `expected_terms` / `expected_doc_ids` 가 없는 케이스(예: abstention(보류))에서 None 이다 — 변형 간 케이스 정렬을 보존하기 위해 pairwise 에서 제외된다.
* Seed 는 bootstrap RNG 만 구동한다; retrieval 자체는 동일 query+index+backend+rrf_k 에 대해 결정적(deterministic)이다 (dense + BM25 + m3 sparse/colbert).
* 카테고리 버킷팅은 `hardcase_categories`(의미 난이도 태그)를 쓴다. 멀티태그 케이스는 여러 버킷에 나타나므로 카테고리별 카운트는 겹치고 paired CI 가 케이스를 공유한다.
* `dense_m3` 이 delta baseline 인 이유: Phase 3.5 는 **의미 임베딩 위에서 multi-channel vs single-channel** 을 격리하기 때문이다. 0 위 delta 는 multi-channel 변형(hybrid 또는 m3)에, 0 아래는 dense 단독에 유리하다.
* **Phase 3 cross-ref + runner 버그 retraction(철회)**: `reports/retrieval/phase3_mode_20260518T032404Z/` 는 3 개 `hybrid_bm25_k{30,60,100}` 변형이 byte-identical 이라 보고하고 이를 BM25 채널 dominance 로 귀인했다. **그 결론은 틀렸다**: Phase 3 runner 가 `retrieve_candidates`(후보 생성만)를 호출하고 2단계 `apply_fusion_and_reranking`(RRF fusion + 최종 top-k)를 누락했다. hybrid + m3 backend 에서 `retrieve_candidates` 는 `score=0.0` placeholder 를 반환하므로 케이스별 순위가 chunk_id 삽입 순서로 붕괴해 모든 k 값이 byte-identical 이 됐다. Phase 3.5 는 wire-up 을 고친다(`run_single_case` 에 두 호출 모두); hashing 인덱스 재측정은 후속이다. Cross-backend delta(hashing `dense` vs `dense_m3`)는 임베딩 패밀리 교체로 confounded 되어 산출하지 않는다.
* **청크 수 caveat**: BGE-M3 인덱스가 HWP/PDF 모두에 `data_list_csv_text` loader 를 썼고(ADR 0049 graceful fallback), doc 당 ~9 청크였다(`kordoc` 전체 추출의 real100 ~264 청크/doc 대비). 26k kordoc 청크를 BGE-M3 로 MPS 에서 재임베딩하면 >2h 걸린다(배치별 GPU dispatch overhead); csv_text fallback 은 build 를 20 분 미만으로 유지하면서 Phase 3.5 내부 paired CI 주장을 보존한다. 이 인덱스의 절대 `chunk_recall@k` 는 Phase 3 의 kordoc 빌드 수치와 직접 비교 불가 — Phase 3.5 내부 delta 만 비교 가능하다.
* **Runner 측 m3 batching (측정 전용 최적화)**: 이 인덱스에서 query 별 colbert max-sim 이 지배적 비용이다(청크별 Python-loop matmul × ~900 청크 × 최적화 전 경로에서 관측된 ~50s/query). runner 는 모든 청크 colbert 벡터를 하나의 `(Σ T_d, 1024)` 행렬로 concat 해 unique query 당 **1회** matmul 후 행별 max+sum 을 위해 컬럼을 청크별로 다시 split 한다. 청크별 경로와 수학적으로 동일하나(각 청크의 컬럼 슬라이스는 독립) ~100× 빠르다. 패치는 runner 에 있다(`_prime_m3_index_cache_and_colbert`); `rag_m3.py` / `rag_retrieval.py` 는 미변경.
* **범위 외**: 채널별 m3 ablation(sparse-only, colbert-only — ADR 0010 'Alternatives considered' 참조); hybrid_bm25 의 RRF-k sweep(Phase 3 이 이미 hashing 에서 k=30/60/100 byte-identical 을 보임); 위에 stack 된 cross-encoder rerank(Phase 4).
* ADR cross-ref: ADR 0010(BGE-M3 multi-channel deferred), ADR 0021(m3_full 분석 행), ADR 0032(torch>=2.6 unblock — 본 측정을 원래 미뤘던 install blocker 를 해소).
* 이 리포트는 `--reaggregate` 로 `reports/retrieval/phase35_m3_20260518T090328Z/raw_results.json` 로부터 재생성됨 — 카테고리는 `hardcase_categories` 에서 재유도; `raw_results.json` 의 retrieval 점수는 주입된 `categories` 필드를 제외하면 byte-for-byte 불변.
