# Phase 3.5 retrieval-eval — m3 검색 모드(mode) ablation (real100 n=221, 의미 임베딩(semantic embeddings))

Run: `20260521-0334-phase35-m3-reaggregate` · commit `5e5f07bc96` · index_dir=`data/index/real100_m3` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## 변형(variants)

| 변형 | backend | RRF k | 문서 | 청크 |
|---|---|---|---|---|
| `dense_m3` | dense | — | 100 | 26376 |
| `hybrid_bm25_k60_m3` | hybrid | 60 | 100 | 26376 |

## 지연시간(latency, ms)

| 변형 | p50 | p95 | mean | n |
|---|---|---|---|---|
| `dense_m3` | 558.865 | 2220.352 | 847.273 | 221 |
| `hybrid_bm25_k60_m3` | 757.248 | 1236.946 | 801.259 | 221 |

## chunk_recall@5

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.248 (n=114) | 0.296 (n=114) |
| multi_hop | 0.196 (n=93) | 0.248 (n=93) |
| distractor_heavy | 0.242 (n=42) | 0.304 (n=42) |
| long_context | 0.293 (n=9) | 0.354 (n=9) |
| no_answer | 0.600 (n=2) | 0.600 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.530 (n=13) | 0.538 (n=13) |

### chunk_recall@5 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.048 (+0.013, +0.088) 유의함 |
| multi_hop | +0.052 (+0.021, +0.092) 유의함 |
| distractor_heavy | +0.062 (+0.003, +0.138) 유의함 |
| long_context | +0.060 (+0.000, +0.172) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.000 (+0.000, +0.000) **유의하지 않음** |
| uncategorized | +0.008 (-0.171, +0.219) **유의하지 않음** |

## chunk_recall@10

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.288 (n=114) | 0.340 (n=114) |
| multi_hop | 0.240 (n=93) | 0.283 (n=93) |
| distractor_heavy | 0.287 (n=42) | 0.354 (n=42) |
| long_context | 0.301 (n=9) | 0.434 (n=9) |
| no_answer | 0.600 (n=2) | 0.600 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.559 (n=13) | 0.620 (n=13) |

### chunk_recall@10 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.052 (+0.020, +0.088) 유의함 |
| multi_hop | +0.043 (+0.018, +0.073) 유의함 |
| distractor_heavy | +0.067 (+0.015, +0.131) 유의함 |
| long_context | +0.133 (+0.017, +0.278) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.000 (+0.000, +0.000) **유의하지 않음** |
| uncategorized | +0.060 (-0.110, +0.256) **유의하지 않음** |

## mrr

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.515 (n=114) | 0.625 (n=114) |
| multi_hop | 0.501 (n=93) | 0.631 (n=93) |
| distractor_heavy | 0.499 (n=42) | 0.581 (n=42) |
| long_context | 0.619 (n=9) | 0.701 (n=9) |
| no_answer | 0.750 (n=2) | 0.750 (n=2) |
| ambiguous_query | 1.000 (n=1) | 0.500 (n=1) |
| uncategorized | 0.579 (n=13) | 0.596 (n=13) |

### mrr — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.110 (+0.056, +0.165) 유의함 |
| multi_hop | +0.130 (+0.073, +0.192) 유의함 |
| distractor_heavy | +0.082 (+0.016, +0.159) 유의함 |
| long_context | +0.082 (+0.011, +0.183) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | -0.500 (-0.500, -0.500) 유의함 |
| uncategorized | +0.018 (-0.191, +0.215) **유의하지 않음** |

## ndcg@10

| 카테고리 | `dense_m3` | `hybrid_bm25_k60_m3` |
|---|---|---|
| overall | 0.318 (n=114) | 0.383 (n=114) |
| multi_hop | 0.277 (n=93) | 0.347 (n=93) |
| distractor_heavy | 0.309 (n=42) | 0.372 (n=42) |
| long_context | 0.417 (n=9) | 0.534 (n=9) |
| no_answer | 0.473 (n=2) | 0.468 (n=2) |
| ambiguous_query | 1.000 (n=1) | 0.631 (n=1) |
| uncategorized | 0.544 (n=13) | 0.573 (n=13) |

### ndcg@10 — `dense_m3` 대비 paired CI delta (seed 평균)

| 카테고리 | `hybrid_bm25_k60_m3` |
|---|---|
| overall | +0.065 (+0.032, +0.099) 유의함 |
| multi_hop | +0.070 (+0.040, +0.106) 유의함 |
| distractor_heavy | +0.063 (+0.007, +0.126) 유의함 |
| long_context | +0.117 (+0.032, +0.223) 유의함 |
| no_answer | -0.005 (-0.010, +0.000) **유의하지 않음** |
| ambiguous_query | -0.369 (-0.369, -0.369) 유의함 |
| uncategorized | +0.029 (-0.140, +0.189) **유의하지 않음** |

## 카테고리별 winner

winner = `chunk_recall@10` 평균이 가장 높으면서 `dense_m3` 대비 paired CI 가 완전히 0 위인 변형. "유의하지 않음" = 어떤 변형의 CI 도 0 을 넘지 못함 (절대 규칙 #5).

| 카테고리 | winner | 평균 recall@10 | `dense_m3` 대비 delta CI |
|---|---|---|---|
| overall | `hybrid_bm25_k60_m3` | 0.340 | +0.052 (+0.020, +0.088) 유의함 |
| multi_hop | `hybrid_bm25_k60_m3` | 0.283 | +0.043 (+0.018, +0.073) 유의함 |
| distractor_heavy | `hybrid_bm25_k60_m3` | 0.354 | +0.067 (+0.015, +0.131) 유의함 |
| long_context | `hybrid_bm25_k60_m3` | 0.434 | +0.133 (+0.017, +0.278) 유의함 |
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
* 이 리포트는 `--reaggregate` 로 `reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/raw_results.json` 로부터 재생성됨 — 카테고리는 `hardcase_categories` 에서 재유도; `raw_results.json` 의 retrieval 점수는 주입된 `categories` 필드를 제외하면 byte-for-byte 불변.
