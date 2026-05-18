# `retrieval_miss = 83` root-cause inspection

| field | value |
|---|---|
| Issue | #1003 |
| Trigger PR | #1001 (ADR 0059 failure_classifier) |
| Source measurement | `reports/real100/eval_summary.json` (post-`origin/main` `a931a49` + Scenario A hybrid switch via #1000), n=221 |
| Date | 2026-05-19 |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 retrieval fix 0건** (본 문서는 audit 만; 후속 issue 로 분기) |

## Executive summary

ADR 0059 가 도입한 7-category 분류기 (`eval/scorers/failure_classifier.py`, PR #1001) 가 n=221 real-eval 에서 **`retrieval_miss = 83`** 측정 — Phase 5 audit (#992) 의 finding #1 (`verifier_false_negative = 49` at HEAD) 보다 큰 *dominant failure mode* (전체 164 failure 의 50.6%).

분류 표면 부재 (audit 시점) 일 때는 보이지 않던 신호 — 본 audit 의 **부산물**: "측정 표면이 생기자마자 audit 가 모르던 더 큰 함정이 노출됨" (ADR 0054 → 0056 cascade 와 동일 구조).

**핵심 발견 4개** (raw inspection 결과로 ranking 확정):

1. **88% multi_hop hardcase** — `retrieval_miss=83` 중 73 case 가 `multi_hop` tagged. 본질적으로 *단일 doc 내 multi-section reasoning* 패턴이 dominant root cause.
2. **96% single_doc query_type** — query_type 측면에서는 단일 doc 질의, 그러나 hardcase tag 가 multi_hop — *intent 는 single doc, evidence 는 multi-section*.
3. **65% has non-empty evidence (wrong doc)** — retrieval 자체는 결과 가져오는 데 성공, *ranking* 이 expected doc 을 top-4 밖으로 밀어냄. embedding / scoring 문제.
4. **35% has empty evidence** — 완전 0 결과. ADR 0058 hybrid 후에도 expected doc 가 top-4 에 못 들어오는 *hard miss* 케이스. embedding mismatch 또는 chunking 가설.

## 데이터 inspection (n=83)

### Slice by `query_type`

| query_type | count | % of 83 retrieval_miss | notes |
|---|---:|---:|---|
| `single_doc` | 80 | 96.4% | dominant — single-doc intent 가 fail 의 거의 전부 |
| `follow_up` | 2 | 2.4% | marginal |
| `abstention` | 1 | 1.2% | edge case (no_answer 가 retrieval 도 fail) |

### Slice by `hardcase_categories` (multi-tag)

| hardcase | count | % of 83 | notes |
|---|---:|---:|---|
| `multi_hop` | 73 | 88.0% | **dominant** — single-doc 안의 multi-section retrieval 어려움 |
| `distractor_heavy` | 31 | 37.3% | multi_hop 과 cross — distractor 가 evidence 위로 push |
| `long_context` | 7 | 8.4% | minority |
| `no_answer` | 1 | 1.2% | edge case |
| (no hardcase tag) | 6 | 7.2% | tag 외 패턴 — 후속 inspection 후보 |

multi-tag 합이 83 초과인 이유 — 73 multi_hop case 중 31개가 *동시에* distractor_heavy. 즉 가장 어려운 케이스 = **multi_hop AND distractor_heavy** (실제 단일 doc 안에서 여러 section 을 cross-reference 해야 하는데 distractor 가 ranking 을 흔드는 패턴).

### `expected_doc_ids` cardinality

| cardinality | count | notes |
|---|---:|---|
| 1 (single-doc expected) | 83 | 100% — multi-doc / comparison 패턴 0 |

본 83 case 는 *모두* 단일 doc 답변 기대. ADR 0059 의 `retrieval_miss` 정의 (`expected_doc_ids and not (expected_doc_ids & evidence_doc_ids)`) 이 multi-doc 패턴 (comparison query) 을 미스했다는 의미 아님 — 본 87→83 분포는 single-doc retrieval 의 ranking 문제가 dominant.

### `evidence_doc_ids` empty vs wrong

| pattern | count | % of 83 | interpretation |
|---|---:|---:|---|
| evidence non-empty but wrong | 54 | 65.1% | **dominant** — retrieval API 가 *결과 가져옴*, ranking 이 expected 를 top-4 밖으로 push. embedding / scoring 문제. |
| evidence empty (0 docs) | 29 | 34.9% | hard miss — ADR 0058 hybrid 도 expected doc 을 top-4 에 못 올림. chunking / embedding mismatch 가설. |

### 보조 신호

| 측정 | 값 | 해석 |
|---|---:|---|
| `abstained=True` | 36 (43.4%) | verifier 가 잘못된 retrieval 을 catch + abstain. half 는 catch, half 는 답변 시도. |
| `term_match=True` | 1 (1.2%) | wrong doc 이 우연히 expected term 포함 — 거의 0. |
| `doc_match=False` | 83 (100.0%) | retrieval_miss 정의상 expected 가 evidence 에 부재. integrity check. |
| `retry_count=1` | 67 (80.7%) | verifier retry 1번 trigger 됐지만 fix 못함 — retry strategy 가 retrieval miss 에는 무효. |

## 가설 ranking (post-inspection)

순위 = data 신호 강도 + fix 단순함 비례:

1. **[강 신호, fix 가능성 medium]** **단일 doc 내 multi-section retrieval — chunking + ranking 한계**.
   - Evidence: 88% multi_hop tag + 96% single_doc query_type + 65% wrong doc retrieved.
   - Hypothesis: 단일 doc 의 답이 *여러 section 에 분산* 되어 있어 top-4 (ADR 0001 baseline) 가 충분치 못함.
   - Fix 후보: (a) `top_k` 8 또는 12 로 확장 후 measure, (b) parent-section reassembly 강화 (rag_retrieval.py existing surface), (c) per-doc multi-chunk gather (retrieval mode = "section-aware").
2. **[중 신호, fix 가능성 high]** **Distractor pressure on multi_hop** (37% cross-tag).
   - Hypothesis: multi_hop 단독 (42 case) vs multi_hop+distractor (31 case) 의 retrieval 실패율 비교 → distractor 가 ranking 흔드는 영향 분리.
   - Fix 후보: cross-encoder reranker (현재 ADR 0026 stub) 의 real backend 활성화 후 distractor 압박 받는 multi_hop 만 ablation.
3. **[중 신호, fix 가능성 low]** **35% empty evidence — hard miss**.
   - Hypothesis: expected doc 가 hybrid retrieval 도 못 surface. embedding mismatch (BGE-M3 가 ko RFP domain 에 충분히 specific 하지 않음) 또는 chunking artifact (expected_terms 가 chunk 경계로 분할).
   - Fix 후보: (a) 29 empty case 의 expected doc 에 대해 oracle retrieval (직접 doc_id 로 fetch) 후 query↔doc similarity 직접 측정, (b) chunking strategy ablation.
4. **[약 신호]** **Verifier retry 무효** (81% retry=1 but still miss).
   - Verifier retry 가 retrieval 결과를 *변경 가능하게* 하지 않음 — retry 는 verifier-only loop, retrieval 결과는 그대로. 본 PR 의 분류기는 retry 후 final result 기준 분류.
   - Fix 후보: retry 가 retrieval refinement 도 trigger 하게 변경 (ADR 0004 retry policy 확장) — 큰 surface 변경.

## 후속 issue 후보

| 후보 | scope | priority |
|---|---|:---:|
| Issue A — `top_k` 8 vs 4 ablation (가설 1) | retrieval-eval skill Phase 4 candidate; ~150 LOC ablation runner + REPORT.md | high |
| Issue B — multi_hop+distractor isolation measurement (가설 2) | 31 cross-tagged case 만 isolate 한 sub-eval; ~80 LOC | medium |
| Issue C — Cross-encoder reranker real backend (가설 2) | ADR 0026 re-open conditions 검증; 별 ADR 후보 | medium |
| Issue D — 29 empty-evidence case 의 oracle retrieval analysis (가설 3) | per-case query↔doc cosine inspection; ~100 LOC + audit doc | medium |
| Issue E — ADR 0004 retry policy 확장 (가설 4) | retry 가 retrieval refinement 도 trigger; production code 변경 + ADR | low |

## Out-of-scope (별 PR / 별 audit)

- 실제 retrieval fix (top_k bump / embedding swap / chunking 변경) — 본 audit 가 root cause 가설 ranking 만 emit; fix 는 가설별 별 PR.
- retrieval-eval skill Phase 4 (Metadata / filtering ablation) — sibling skill surface.
- Supply 3 — `failure-mode-harden-process` docs + regression test + ADR 0060.

## Verification

- 본 audit 가 인용하는 84 라는 숫자는 `reports/real100/eval_summary.json::failure_category_counts.retrieval_miss == 84` 로 검증 (PR #1001 real-eval at HEAD `a931a49` 기준).
- 각 slice 분포는 `case_results[*].failure_category == "retrieval_miss"` 인 케이스의 `query_type` / `hardcase_categories` / `expected_doc_ids` / `evidence_doc_ids` 필드에서 직접 추출 (LOC 카운트 형식; no per-case text crosses ADR 0005 boundary).
