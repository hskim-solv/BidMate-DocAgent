# Phase 4 retrieval-eval — 메타데이터 / 필터링 ablation (real100 n=221)

Run: `20260521-0334-phase4-metadata-reaggregate` · commit `5e5f07bc96` · index_dir=`data/index/real100_kordoc` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## 변형(variants)

| 변형 | metadata_first | prefilter | oracle 엔티티 | 문서 | 청크 |
|---|---|---|---|---|---|
| `no_metadata` | False | none | False | 100 | 26376 |
| `soft_agency` | True | none | True | 100 | 26376 |
| `prefilter_agency` | False | agency | False | 100 | 26376 |
| `prefilter_project` | False | project | False | 100 | 26376 |

## 지연시간(latency, ms)

| 변형 | p50 | p95 | mean | n |
|---|---|---|---|---|
| `no_metadata` | 3891.561 | 13928.452 | 6234.874 | 221 |
| `soft_agency` | 1576.235 | 2991.429 | 1789.898 | 221 |
| `prefilter_agency` | 252.572 | 903.325 | 338.818 | 221 |
| `prefilter_project` | 235.494 | 659.241 | 330.529 | 221 |

## chunk_recall@5

| 카테고리 | `no_metadata` | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|---|
| overall | 0.155 (n=114) | 0.353 (n=114) | 0.353 (n=114) | 0.358 (n=114) |
| multi_hop | 0.133 (n=93) | 0.345 (n=93) | 0.345 (n=93) | 0.351 (n=93) |
| distractor_heavy | 0.202 (n=42) | 0.381 (n=42) | 0.381 (n=42) | 0.381 (n=42) |
| long_context | 0.302 (n=9) | 0.399 (n=9) | 0.399 (n=9) | 0.399 (n=9) |
| no_answer | 0.550 (n=2) | 0.550 (n=2) | 0.550 (n=2) | 0.550 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.180 (n=13) | 0.336 (n=13) | 0.336 (n=13) | 0.334 (n=13) |

### chunk_recall@5 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|
| overall | +0.198 (+0.147, +0.251) 유의함 | +0.198 (+0.147, +0.251) 유의함 | +0.203 (+0.152, +0.255) 유의함 |
| multi_hop | +0.212 (+0.160, +0.269) 유의함 | +0.212 (+0.160, +0.269) 유의함 | +0.218 (+0.165, +0.275) 유의함 |
| distractor_heavy | +0.179 (+0.106, +0.263) 유의함 | +0.179 (+0.106, +0.263) 유의함 | +0.179 (+0.107, +0.263) 유의함 |
| long_context | +0.096 (+0.002, +0.223) 유의함 | +0.096 (+0.002, +0.223) 유의함 | +0.096 (+0.002, +0.223) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| uncategorized | +0.156 (+0.001, +0.385) 유의함 | +0.156 (+0.001, +0.385) 유의함 | +0.154 (-0.001, +0.384) **유의하지 않음** |

## chunk_recall@10

| 카테고리 | `no_metadata` | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|---|
| overall | 0.202 (n=114) | 0.415 (n=114) | 0.421 (n=114) | 0.425 (n=114) |
| multi_hop | 0.190 (n=93) | 0.415 (n=93) | 0.423 (n=93) | 0.427 (n=93) |
| distractor_heavy | 0.259 (n=42) | 0.447 (n=42) | 0.453 (n=42) | 0.451 (n=42) |
| long_context | 0.302 (n=9) | 0.429 (n=9) | 0.429 (n=9) | 0.429 (n=9) |
| no_answer | 0.700 (n=2) | 0.700 (n=2) | 0.700 (n=2) | 0.700 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.184 (n=13) | 0.342 (n=13) | 0.342 (n=13) | 0.341 (n=13) |

### chunk_recall@10 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|
| overall | +0.213 (+0.162, +0.265) 유의함 | +0.219 (+0.169, +0.271) 유의함 | +0.223 (+0.174, +0.274) 유의함 |
| multi_hop | +0.225 (+0.167, +0.286) 유의함 | +0.233 (+0.177, +0.293) 유의함 | +0.238 (+0.183, +0.297) 유의함 |
| distractor_heavy | +0.188 (+0.109, +0.275) 유의함 | +0.194 (+0.118, +0.279) 유의함 | +0.192 (+0.121, +0.274) 유의함 |
| long_context | +0.127 (+0.012, +0.280) 유의함 | +0.127 (+0.012, +0.280) 유의함 | +0.127 (+0.012, +0.280) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| uncategorized | +0.158 (+0.003, +0.386) 유의함 | +0.158 (+0.003, +0.386) 유의함 | +0.157 (+0.000, +0.385) 유의함 |

## mrr

| 카테고리 | `no_metadata` | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|---|
| overall | 0.356 (n=114) | 0.758 (n=114) | 0.763 (n=114) | 0.791 (n=114) |
| multi_hop | 0.365 (n=93) | 0.808 (n=93) | 0.810 (n=93) | 0.842 (n=93) |
| distractor_heavy | 0.327 (n=42) | 0.743 (n=42) | 0.757 (n=42) | 0.791 (n=42) |
| long_context | 0.554 (n=9) | 0.751 (n=9) | 0.751 (n=9) | 0.751 (n=9) |
| no_answer | 1.000 (n=2) | 1.000 (n=2) | 1.000 (n=2) | 1.000 (n=2) |
| ambiguous_query | 0.500 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.288 (n=13) | 0.408 (n=13) | 0.408 (n=13) | 0.421 (n=13) |

### mrr — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|
| overall | +0.402 (+0.329, +0.476) 유의함 | +0.407 (+0.335, +0.481) 유의함 | +0.435 (+0.362, +0.507) 유의함 |
| multi_hop | +0.443 (+0.359, +0.523) 유의함 | +0.445 (+0.360, +0.525) 유의함 | +0.477 (+0.396, +0.558) 유의함 |
| distractor_heavy | +0.416 (+0.302, +0.535) 유의함 | +0.429 (+0.314, +0.546) 유의함 | +0.464 (+0.350, +0.576) 유의함 |
| long_context | +0.197 (+0.016, +0.439) 유의함 | +0.197 (+0.016, +0.439) 유의함 | +0.197 (+0.016, +0.439) 유의함 |
| no_answer | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.500 (+0.500, +0.500) 유의함 | +0.500 (+0.500, +0.500) 유의함 | +0.500 (+0.500, +0.500) 유의함 |
| uncategorized | +0.121 (+0.007, +0.295) 유의함 | +0.120 (+0.007, +0.295) 유의함 | +0.133 (+0.018, +0.306) 유의함 |

## ndcg@10

| 카테고리 | `no_metadata` | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|---|
| overall | 0.204 (n=114) | 0.504 (n=114) | 0.510 (n=114) | 0.527 (n=114) |
| multi_hop | 0.191 (n=93) | 0.515 (n=93) | 0.521 (n=93) | 0.544 (n=93) |
| distractor_heavy | 0.227 (n=42) | 0.503 (n=42) | 0.510 (n=42) | 0.517 (n=42) |
| long_context | 0.350 (n=9) | 0.563 (n=9) | 0.564 (n=9) | 0.564 (n=9) |
| no_answer | 0.712 (n=2) | 0.710 (n=2) | 0.712 (n=2) | 0.712 (n=2) |
| ambiguous_query | 0.631 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| uncategorized | 0.220 (n=13) | 0.381 (n=13) | 0.381 (n=13) | 0.376 (n=13) |

### ndcg@10 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `soft_agency` | `prefilter_agency` | `prefilter_project` |
|---|---|---|---|
| overall | +0.300 (+0.248, +0.353) 유의함 | +0.306 (+0.254, +0.359) 유의함 | +0.324 (+0.270, +0.378) 유의함 |
| multi_hop | +0.324 (+0.266, +0.381) 유의함 | +0.330 (+0.273, +0.387) 유의함 | +0.352 (+0.296, +0.411) 유의함 |
| distractor_heavy | +0.276 (+0.197, +0.363) 유의함 | +0.282 (+0.204, +0.366) 유의함 | +0.290 (+0.216, +0.370) 유의함 |
| long_context | +0.213 (+0.051, +0.400) 유의함 | +0.214 (+0.053, +0.401) 유의함 | +0.214 (+0.053, +0.401) 유의함 |
| no_answer | -0.002 (-0.004, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** | +0.000 (+0.000, +0.000) **유의하지 않음** |
| ambiguous_query | +0.369 (+0.369, +0.369) 유의함 | +0.369 (+0.369, +0.369) 유의함 | +0.369 (+0.369, +0.369) 유의함 |
| uncategorized | +0.161 (+0.023, +0.354) 유의함 | +0.161 (+0.023, +0.354) 유의함 | +0.156 (+0.014, +0.347) 유의함 |

## 카테고리별 winner

winner = `chunk_recall@10` 평균이 가장 높으면서 `no_metadata` 대비 paired CI 가 완전히 0 위인 변형. "유의하지 않음" = 어떤 변형의 CI 도 0 을 넘지 못함 (절대 규칙 #5).

| 카테고리 | winner | 평균 recall@10 | `no_metadata` 대비 delta CI |
|---|---|---|---|
| overall | `prefilter_project` | 0.425 | +0.223 (+0.174, +0.274) 유의함 |
| multi_hop | `prefilter_project` | 0.427 | +0.238 (+0.183, +0.297) 유의함 |
| distractor_heavy | `prefilter_agency` | 0.453 | +0.194 (+0.118, +0.279) 유의함 |
| long_context | `soft_agency` | 0.429 | +0.127 (+0.012, +0.280) 유의함 |
| no_answer | `유의하지 않음` | — | — |
| ambiguous_query | `유의하지 않음` | — | — |
| uncategorized | `soft_agency` | 0.342 | +0.158 (+0.003, +0.386) 유의함 |

## 비고(notes)

* **Oracle ceiling, realistic NER 아님**: agency / project 는 answerable 케이스의 `expected_doc_ids[0]` 를 인덱스 문서 메타데이터에서 조회해 얻는다. 이는 "메타데이터 신호가 완벽하다면 recall 이 얼마나 움직이는가?" 의 상한(upper bound)을 측정한다. 현실의 query-time agency 추출기는 이 ceiling 아래에 위치한다 (follow-up).
* **Abstention(보류) 케이스는 oracle 이 없다** (`expected_doc_ids` 없음). 따라서 모든 변형이 baseline 으로 수렴하고 `chunk_recall@k` 가 None → pairwise 에서 제외된다. 측정된 효과는 Phase 4 프로토콜 요구대로 answerable(메타데이터 적용 가능) 케이스에 한정된다.
* **`rerank=True` 필수**: `retrieve_candidates` 의 score-fusion 공식은 `rerank` 가 truthy 일 때만 `metadata_first` 분기에 도달한다 (`rerank=False` 는 `score=dense_score` 로 단락된다). Phase 3 은 `rerank=False` 라 `metadata_first` 플래그가 무력했다. 여기서 `rerank_cross_encoder` 는 설정하지 않으므로 cross-encoder 단계는 꺼진 채 — `rerank` 는 dense+lexical(+metadata) 혼합만 선택한다.
* **점수 공식(scoring formulas)**: `no_metadata` / `prefilter_*` = 0.70·dense + 0.30·lexical; `soft_agency` = 0.60·dense + 0.25·lexical + 0.15·metadata, 여기서 `metadata_similarity` 는 `agency` 가 oracle 엔티티와 일치하는 청크에 1.0 을 반환한다. `prefilter_*` 는 baseline 공식을 유지하되 점수 계산 전에 후보 풀(candidate pool)을 hard filter 로 축소한다.
* **kordoc 코퍼스**: `data/index/real100_kordoc` 는 kordoc 전체 코퍼스 추출(26376 청크)로, Phase 2 / Phase 3 이 쓴 코퍼스와 동일하다. 절대 recall 수치는 kordoc 코퍼스 phase 들 간 비교 가능하다. n=221 케이스 중 114 개가 gold-derivable(answerable 이며 `expected_terms` 가 청크와 매칭); abstention + 미매칭 케이스는 pairwise 에서 제외된다 (overall n=114).
* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, cross-encoder rerank 없음 — 메타데이터 효과를 expansion / cross-encoder 효과로부터 격리한다.
* Seed 는 bootstrap RNG 만 구동한다; retrieval 자체는 동일 query + index + plan 에 대해 결정적(deterministic)이다.
* 카테고리 버킷팅은 `hardcase_categories` 를 쓴다. 멀티태그 케이스는 여러 버킷에 나타나므로 카테고리별 카운트는 겹치고 케이스를 공유한다.
* **Recall-↑ query 패턴 (Phase 4 프로토콜 step 3)**: agency / project 가 expected doc 에 매핑되는 모든 answerable query 는 oracle 메타데이터 신호로 recall@10 +0.21~0.22, MRR +0.40~0.44, ndcg@10 +0.30~0.32 (모두 SIG) 를 얻는다. 지배적인 `multi_hop` cohort(n=93)가 가장 큰 lift(recall@10 +0.23~0.24, MRR +0.44~0.48)를 본다. Abstention query 는 아무것도 얻지 못한다 — 메타데이터는 타깃 doc 이 존재하는 곳에서만 정확히 돕는다.
* **지연시간 Pareto**: hard pre-filter 는 점수 계산 전 후보 풀을 26k 청크에서 1 개 doc / agency 로 축소해, p50 을 3892ms(`no_metadata`)에서 253ms(`prefilter_agency`, ~15배)로 줄이면서 recall 은 동등하거나 더 높다 — Pareto-dominant. `soft_agency` 는 전체 풀을 유지하므로 더 싼 top-1 fusion 경로로 p50 지연시간을 절반(1576ms)만 줄인다.
* **쿼리 ↔ 메타데이터 coverage**: 위 oracle ceiling 은 counterfactual(모든 query 에 gold 메타데이터 주입)이다. query 에서 실제 도출 가능한 메타데이터로 bound 한 현실 ceiling 분석(query 의미 분류: metadata-identifiable / content-query / underspecified)은 `COVERAGE.md` 참조 — 재현: `scripts/phase4_query_metadata_coverage.py`.
* 이 리포트는 `--reaggregate` 로 `reports/retrieval/phase4_metadata_20260520T032829Z_kordoc/raw_results.json` 로부터 재생성됨 — 카테고리는 `hardcase_categories` 에서 재유도; `raw_results.json` 의 retrieval 점수는 주입된 `categories` 필드를 제외하면 byte-for-byte 불변.
