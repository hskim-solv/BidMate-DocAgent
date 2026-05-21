# Phase 4 retrieval-eval — 현실 query-time 메타데이터 라우팅(realistic routing) (real100 n=221)

Run: `20260521-0257-phase4-realistic-reaggregate` · commit `f4600721a9` · index_dir=`data/index/real100_kordoc` · eval_config=`eval/real_config.local.yaml` · seeds=[17, 23, 29] · top_k=20 · ks=[5, 10]

## 변형(variants)

| 변형 | metadata_first | prefilter | 추출 엔티티 주입 | 문서 | 청크 |
|---|---|---|---|---|---|
| `no_metadata` | False | none | False | 100 | 26376 |
| `extractor_soft_agency` | True | none | True | 100 | 26376 |
| `extractor_prefilter_agency` | False | agency | False | 100 | 26376 |
| `extractor_prefilter_project` | False | project | False | 100 | 26376 |

## 추출 품질(extraction quality, gold 대비)

현실 추출기(`match_metadata_targets`)가 query 텍스트만으로 도출한 agency / project 를 정답(gold, `expected_doc_ids[0]`)과 비교. recall = 정답 대비 정확 추출 비율(= 현실 라우팅 coverage), precision = 추출한 것 중 정확 비율.

| 필드 | answerable n | 추출 n | 정확 n | recall | precision |
|---|---|---|---|---|---|
| agency | 217 | 17 | 16 | 0.074 | 0.941 |
| project | 217 | 60 | 32 | 0.147 | 0.533 |

follow_up cohort: n=4, agency 정확 추출 1 (단일 query 만 보므로 context 의존 follow_up 은 추출 신호가 약함 — ADR 0065 decision #3 의 cohort 분리).

## 지연시간(latency, ms)

| 변형 | p50 | p95 | mean | n |
|---|---|---|---|---|
| `no_metadata` | 1681.772 | 10960.995 | 3087.747 | 221 |
| `extractor_soft_agency` | 2332.266 | 16663.5 | 4792.217 | 221 |
| `extractor_prefilter_agency` | 2035.938 | 10527.55 | 3224.077 | 221 |
| `extractor_prefilter_project` | 2228.732 | 46380.759 | 7954.445 | 221 |

## chunk_recall@5

| 카테고리 | `no_metadata` | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|---|
| overall | 0.155 (n=114) | 0.156 (n=114) | 0.156 (n=114) | 0.149 (n=114) |
| extractor_hit_agency | 0.278 (n=12) | 0.285 (n=12) | 0.285 (n=12) | 0.283 (n=12) |
| extractor_miss_agency | 0.141 (n=102) | 0.141 (n=102) | 0.141 (n=102) | 0.133 (n=102) |
| multi_hop | 0.133 (n=93) | 0.134 (n=93) | 0.134 (n=93) | 0.125 (n=93) |
| distractor_heavy | 0.202 (n=42) | 0.204 (n=42) | 0.204 (n=42) | 0.188 (n=42) |
| long_context | 0.302 (n=9) | 0.302 (n=9) | 0.302 (n=9) | 0.299 (n=9) |
| no_answer | 0.550 (n=2) | 0.550 (n=2) | 0.550 (n=2) | 0.550 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| follow_up | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) |
| uncategorized | 0.180 (n=13) | 0.182 (n=13) | 0.182 (n=13) | 0.180 (n=13) |

### chunk_recall@5 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|
| overall | +0.000 (-0.000, +0.002) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.002) **NOT SIGNIFICANT** | -0.006 (-0.017, +0.004) **NOT SIGNIFICANT** |
| extractor_hit_agency | +0.007 (+0.000, +0.017) **NOT SIGNIFICANT** | +0.007 (+0.000, +0.017) **NOT SIGNIFICANT** | +0.005 (+0.000, +0.015) **NOT SIGNIFICANT** |
| extractor_miss_agency | -0.000 (-0.001, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.007 (-0.019, +0.003) **NOT SIGNIFICANT** |
| multi_hop | +0.000 (-0.001, +0.002) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.002) **NOT SIGNIFICANT** | -0.008 (-0.022, +0.004) **NOT SIGNIFICANT** |
| distractor_heavy | +0.001 (+0.000, +0.004) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.004) **NOT SIGNIFICANT** | -0.015 (-0.041, +0.004) **NOT SIGNIFICANT** |
| long_context | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.004 (-0.011, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| follow_up | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.002 (+0.000, +0.005) **NOT SIGNIFICANT** | +0.002 (+0.000, +0.005) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |

## chunk_recall@10

| 카테고리 | `no_metadata` | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|---|
| overall | 0.202 (n=114) | 0.201 (n=114) | 0.203 (n=114) | 0.196 (n=114) |
| extractor_hit_agency | 0.288 (n=12) | 0.297 (n=12) | 0.297 (n=12) | 0.292 (n=12) |
| extractor_miss_agency | 0.192 (n=102) | 0.190 (n=102) | 0.192 (n=102) | 0.184 (n=102) |
| multi_hop | 0.190 (n=93) | 0.188 (n=93) | 0.191 (n=93) | 0.182 (n=93) |
| distractor_heavy | 0.259 (n=42) | 0.256 (n=42) | 0.261 (n=42) | 0.241 (n=42) |
| long_context | 0.302 (n=9) | 0.302 (n=9) | 0.302 (n=9) | 0.299 (n=9) |
| no_answer | 0.700 (n=2) | 0.700 (n=2) | 0.700 (n=2) | 0.700 (n=2) |
| ambiguous_query | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) | 1.000 (n=1) |
| follow_up | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) |
| uncategorized | 0.184 (n=13) | 0.188 (n=13) | 0.188 (n=13) | 0.184 (n=13) |

### chunk_recall@10 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|
| overall | -0.001 (-0.005, +0.002) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.003) **NOT SIGNIFICANT** | -0.007 (-0.019, +0.004) **NOT SIGNIFICANT** |
| extractor_hit_agency | +0.010 (+0.000, +0.024) **NOT SIGNIFICANT** | +0.010 (+0.000, +0.024) **NOT SIGNIFICANT** | +0.005 (+0.000, +0.015) **NOT SIGNIFICANT** |
| extractor_miss_agency | -0.002 (-0.007, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.008 (-0.022, +0.004) **NOT SIGNIFICANT** |
| multi_hop | -0.002 (-0.007, +0.001) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.002) **NOT SIGNIFICANT** | -0.008 (-0.025, +0.005) **NOT SIGNIFICANT** |
| distractor_heavy | -0.003 (-0.014, +0.004) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.004) **NOT SIGNIFICANT** | -0.018 (-0.050, +0.004) **NOT SIGNIFICANT** |
| long_context | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.004 (-0.011, +0.000) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| follow_up | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.004 (+0.000, +0.013) **NOT SIGNIFICANT** | +0.004 (+0.000, +0.013) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |

## mrr

| 카테고리 | `no_metadata` | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|---|
| overall | 0.356 (n=114) | 0.354 (n=114) | 0.357 (n=114) | 0.335 (n=114) |
| extractor_hit_agency | 0.399 (n=12) | 0.410 (n=12) | 0.414 (n=12) | 0.410 (n=12) |
| extractor_miss_agency | 0.351 (n=102) | 0.348 (n=102) | 0.351 (n=102) | 0.326 (n=102) |
| multi_hop | 0.365 (n=93) | 0.363 (n=93) | 0.366 (n=93) | 0.332 (n=93) |
| distractor_heavy | 0.327 (n=42) | 0.325 (n=42) | 0.330 (n=42) | 0.312 (n=42) |
| long_context | 0.554 (n=9) | 0.548 (n=9) | 0.554 (n=9) | 0.536 (n=9) |
| no_answer | 1.000 (n=2) | 1.000 (n=2) | 1.000 (n=2) | 1.000 (n=2) |
| ambiguous_query | 0.500 (n=1) | 0.500 (n=1) | 0.500 (n=1) | 0.500 (n=1) |
| follow_up | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) |
| uncategorized | 0.288 (n=13) | 0.292 (n=13) | 0.292 (n=13) | 0.282 (n=13) |

### mrr — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|
| overall | -0.002 (-0.004, +0.001) **NOT SIGNIFICANT** | +0.002 (+0.000, +0.004) **NOT SIGNIFICANT** | -0.021 (-0.057, +0.013) **NOT SIGNIFICANT** |
| extractor_hit_agency | +0.011 (+0.000, +0.026) **NOT SIGNIFICANT** | +0.015 (+0.000, +0.037) **NOT SIGNIFICANT** | +0.010 (+0.000, +0.031) **NOT SIGNIFICANT** |
| extractor_miss_agency | -0.003 (-0.006, -0.001) significant | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.025 (-0.063, +0.013) **NOT SIGNIFICANT** |
| multi_hop | -0.002 (-0.004, +0.001) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.004) **NOT SIGNIFICANT** | -0.033 (-0.075, +0.005) **NOT SIGNIFICANT** |
| distractor_heavy | -0.003 (-0.009, +0.003) **NOT SIGNIFICANT** | +0.003 (+0.000, +0.009) **NOT SIGNIFICANT** | -0.016 (-0.081, +0.042) **NOT SIGNIFICANT** |
| long_context | -0.006 (-0.017, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.018 (-0.083, +0.030) **NOT SIGNIFICANT** |
| no_answer | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| follow_up | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.004 (-0.001, +0.012) **NOT SIGNIFICANT** | +0.004 (+0.000, +0.012) **NOT SIGNIFICANT** | -0.006 (-0.018, +0.000) **NOT SIGNIFICANT** |

## ndcg@10

| 카테고리 | `no_metadata` | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|---|
| overall | 0.204 (n=114) | 0.206 (n=114) | 0.209 (n=114) | 0.194 (n=114) |
| extractor_hit_agency | 0.328 (n=12) | 0.373 (n=12) | 0.374 (n=12) | 0.336 (n=12) |
| extractor_miss_agency | 0.189 (n=102) | 0.186 (n=102) | 0.189 (n=102) | 0.177 (n=102) |
| multi_hop | 0.191 (n=93) | 0.190 (n=93) | 0.193 (n=93) | 0.177 (n=93) |
| distractor_heavy | 0.227 (n=42) | 0.226 (n=42) | 0.230 (n=42) | 0.213 (n=42) |
| long_context | 0.350 (n=9) | 0.344 (n=9) | 0.350 (n=9) | 0.339 (n=9) |
| no_answer | 0.712 (n=2) | 0.710 (n=2) | 0.712 (n=2) | 0.712 (n=2) |
| ambiguous_query | 0.631 (n=1) | 0.631 (n=1) | 0.631 (n=1) | 0.631 (n=1) |
| follow_up | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) | 0.000 (n=3) |
| uncategorized | 0.220 (n=13) | 0.256 (n=13) | 0.256 (n=13) | 0.220 (n=13) |

### ndcg@10 — `no_metadata` 대비 paired CI delta (seed 평균)

| 카테고리 | `extractor_soft_agency` | `extractor_prefilter_agency` | `extractor_prefilter_project` |
|---|---|---|---|
| overall | +0.002 (-0.004, +0.012) **NOT SIGNIFICANT** | +0.005 (+0.000, +0.014) **NOT SIGNIFICANT** | -0.010 (-0.027, +0.007) **NOT SIGNIFICANT** |
| extractor_hit_agency | +0.045 (+0.000, +0.126) **NOT SIGNIFICANT** | +0.046 (+0.000, +0.128) **NOT SIGNIFICANT** | +0.008 (+0.000, +0.025) **NOT SIGNIFICANT** |
| extractor_miss_agency | -0.003 (-0.005, -0.001) significant | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.012 (-0.031, +0.006) **NOT SIGNIFICANT** |
| multi_hop | -0.002 (-0.005, +0.001) **NOT SIGNIFICANT** | +0.001 (+0.000, +0.003) **NOT SIGNIFICANT** | -0.014 (-0.036, +0.005) **NOT SIGNIFICANT** |
| distractor_heavy | -0.001 (-0.008, +0.005) **NOT SIGNIFICANT** | +0.002 (+0.000, +0.007) **NOT SIGNIFICANT** | -0.014 (-0.051, +0.013) **NOT SIGNIFICANT** |
| long_context | -0.006 (-0.012, -0.001) significant | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | -0.011 (-0.032, +0.000) **NOT SIGNIFICANT** |
| no_answer | -0.002 (-0.004, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| ambiguous_query | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| follow_up | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |
| uncategorized | +0.035 (+0.000, +0.106) **NOT SIGNIFICANT** | +0.035 (+0.000, +0.106) **NOT SIGNIFICANT** | +0.000 (+0.000, +0.000) **NOT SIGNIFICANT** |

## 카테고리별 winner

winner = `chunk_recall@10` 평균이 가장 높으면서 `no_metadata` 대비 paired CI 가 완전히 0 위인 변형. "NOT SIGNIFICANT" = 어떤 변형의 CI 도 0 을 넘지 못함 (절대 규칙 #5).

| 카테고리 | winner | 평균 recall@10 | `no_metadata` 대비 delta CI |
|---|---|---|---|
| overall | `NOT SIGNIFICANT` | — | — |
| extractor_hit_agency | `NOT SIGNIFICANT` | — | — |
| extractor_miss_agency | `NOT SIGNIFICANT` | — | — |
| multi_hop | `NOT SIGNIFICANT` | — | — |
| distractor_heavy | `NOT SIGNIFICANT` | — | — |
| long_context | `NOT SIGNIFICANT` | — | — |
| no_answer | `NOT SIGNIFICANT` | — | — |
| ambiguous_query | `NOT SIGNIFICANT` | — | — |
| follow_up | `NOT SIGNIFICANT` | — | — |
| uncategorized | `NOT SIGNIFICANT` | — | — |

## 비고(notes)

* **결론 (NULL-WINNER)**: 위 추출 품질 표의 agency recall 과 카테고리별 winner 표가 보여주듯, 현실 추출기는 answerable cohort 의 소수에서만 정답 agency 를 회수하며(coverage 분석의 char-4gram proxy ~34% 보다 낮다 — 운영 matcher 는 compact-contains / 강한 토큰 중첩을 요구), 회수에 성공한 cohort(`extractor_hit_agency`)에서도 oracle ceiling(PR #1108, recall@10 +0.22)을 통계적으로 회복하지 못한다(모든 카테고리 NOT SIGNIFICANT). 이는 ADR 0065 의 "메타데이터 라우팅 = 좁은 opt-in 부가 기능, 운영 기본값 변경 아님" 결정을 측정으로 지지한다. 또한 `extractor_prefilter_project` 는 oracle 의 ~15배 지연시간 Pareto 와 달리 부정확한 project 매칭으로 p95 지연시간이 오히려 악화된다 — hard project 필터의 이득은 현실 추출 정밀도에 종속된다.
* **현실 추출기, oracle 아님**: agency / project 는 `match_metadata_targets` 가 query 텍스트만으로 corpus catalog(`metadata_targets`)에 매칭해 도출한다 (gold 미사용, 결정적, 새 의존성 0). gold 는 추출 품질 채점에만 쓰고 retrieval 에 주입하지 않는다. 이 측정의 delta 는 oracle ceiling(PR #1108, recall@10 +0.21~0.22) 대비 **실제 회수율**이다 — ADR 0065 decision #3.
* **`extractor_hit_agency` cohort**: 추출기가 정답 agency 를 맞춘 케이스. oracle 의 ~34% metadata-identifiable cohort 의 현실 대응물 — 추출이 성공한 곳에서의 retrieval lift 를 보여준다. `extractor_miss_agency` = gold 는 있으나 추출 실패(라우팅 신호 없음 → baseline 으로 수렴).
* **False-positive 라우팅 위험**: 잘못 추출된 agency 로 hard pre-filter 시 정답 doc 이 후보 풀에서 제거될 수 있다 → overall delta 가 음수일 수 있어 `extractor_hit_agency` / `extractor_miss_agency` cohort 를 분리 보고한다.
* **follow_up cohort 분리**: `match_metadata_targets` 는 단일 query 만 보므로 context 의존 follow_up 의 추출 신호가 약하다. 별도 cohort 로 분리해 혼입 방지(ADR 0065 decision #3).
* **`rerank=True` 필수**: oracle runner 와 동일 — score-fusion 공식은 `rerank` 가 truthy 일 때만 `metadata_first` 분기에 도달한다. `rerank_cross_encoder` 는 설정하지 않으므로 cross-encoder 단계는 꺼진 채다.
* **kordoc 코퍼스**: `data/index/real100_kordoc` 는 kordoc 전체 코퍼스 추출(26376 청크)로 PR #1108 oracle 측정과 동일 인덱스 — delta 직접 비교 가능.
* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, cross-encoder rerank 없음 — 메타데이터 효과를 격리한다.
* Seed 는 bootstrap RNG 만 구동한다; retrieval + 추출은 동일 query + index + plan 에 대해 결정적이다.
* 이 리포트는 `--reaggregate` 로 `reports/retrieval/phase4_realistic_metadata_20260521T013224Z_kordoc/raw_results.json` 로부터 재생성됨 — hardcase / follow_up 카테고리는 eval_config 에서, extractor cohort 태그는 raw row 의 `agency_match` 에서 재유도; retrieval 점수는 byte-identical 불변.
