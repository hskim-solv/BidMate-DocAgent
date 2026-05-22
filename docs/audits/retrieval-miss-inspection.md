# `retrieval_miss` 근본 원인(root-cause) inspection

> **정합(reconcile) 노트 — #1245 (2026-05-22).** 정본 2026-05-19 baseline
> run(`de69c5c2`, n=221) 기준 `retrieval_miss = 64` (전체 **180** failure 중 35.6%),
> `verifier_false_negative = 76` 이 **더 큰** failure mode 다. 단일 출처:
> `reports/real100/baseline.aggregate.json` + `reports/real100/failure_distribution.aggregate.json`.
> 따라서 아래 본문의 "retrieval_miss = dominant mode (50.6%)" 서술은 정본에서 더 이상
> 성립하지 않는다 (요약 정정 참조).
>
> 아래 "데이터 inspection" 의 per-case 슬라이스(query_type / hardcase / evidence / 보조 신호)는
> earlier `a931a49` run (당시 `retrieval_miss = 83`) 스냅샷으로 **보존**한다 — 어떤 종류의
> retrieval 이 실패하는지에 대한 진단 가치 때문. 정본 run 기준 슬라이스 재계산은 per-case
> `eval_summary.json`(gitignored, local-only)이 필요해 별도 follow-up(real-eval run 1회) 관할이며
> 본 issue(#1245, 새 측정 없이 aggregate 정합) 범위 밖이다.

| field | value |
|---|---|
| Issue | #1003 |
| Trigger PR | #1001 (ADR 0059 failure_classifier) |
| Source measurement | `reports/real100/eval_summary.json` (post-`origin/main` `a931a49` + Scenario A hybrid switch via #1000), n=221 |
| Date | 2026-05-19 |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 retrieval fix 0건** (본 문서는 audit 만; 후속 issue 로 분기) |

## 요약(Executive summary)

ADR 0059 가 도입한 7-category 분류기 (`eval/scorers/failure_classifier.py`, PR #1001) 의 inspection. 본 문서의 per-case 슬라이스는 earlier `a931a49` run (당시 `retrieval_miss = 83`, 전체 164 failure 의 50.6%) 에서 추출됐다. **정본 2026-05-19 baseline (`de69c5c2`) 기준으로는 `retrieval_miss = 64` (전체 180 failure 중 35.6%) 이며, `verifier_false_negative = 76` 이 더 큰 failure mode 다** — 즉 아래 슬라이스가 전제하던 "retrieval_miss = dominant mode" 서술은 정본에서 성립하지 않는다 (상단 정합 노트 참조). 본 문서는 *어떤 종류의 retrieval 이 실패하는가* 의 슬라이스 패턴 진단 가치 때문에 보존하되, headline 비중은 정본 수치(64)로 읽어야 한다.

분류 표면 부재 (audit 시점) 일 때는 보이지 않던 신호 — 본 audit 의 **부산물**: "측정 표면이 생기자마자 audit 가 모르던 더 큰 함정이 노출됨" (ADR 0054 → 0056 cascade 와 동일 구조).

**핵심 발견 4개** (raw inspection 결과로 ranking 확정):

1. **88% multi_hop hardcase** — `retrieval_miss=83` 중 73 case 가 `multi_hop` tagged. 본질적으로 *단일 doc 내 multi-section reasoning* 패턴이 dominant root cause.
2. **96% single_doc query_type** — query_type 측면에서는 단일 doc 질의, 그러나 hardcase tag 가 multi_hop — *intent 는 single doc, evidence 는 multi-section*.
3. **65% has non-empty evidence (wrong doc)** — retrieval 자체는 결과 가져오는 데 성공, *ranking* 이 expected doc 을 top-4 밖으로 밀어냄. embedding / scoring 문제.
4. **35% has empty evidence** — 완전 0 결과. ADR 0058 hybrid 후에도 expected doc 가 top-4 에 못 들어오는 *hard miss* 케이스. embedding mismatch 또는 chunking 가설.

## 데이터 inspection (n=83, `a931a49` snapshot)

> 아래 슬라이스 표는 모두 earlier `a931a49` run(`retrieval_miss = 83`) 의 per-case 분포다 (정본 `de69c5c2` run 의 64 가 아님). 상단 정합 노트 참조 — 표 내부 수치는 서로 일관(같은 run)하나 headline 64 와는 run 이 다르다.

### `query_type` 별 slice

| query_type | count | % of 83 retrieval_miss | notes |
|---|---:|---:|---|
| `single_doc` | 80 | 96.4% | dominant — single-doc intent 가 fail 의 거의 전부 |
| `follow_up` | 2 | 2.4% | marginal |
| `abstention` | 1 | 1.2% | edge case (no_answer 가 retrieval 도 fail) |

### `hardcase_categories` 별 slice (multi-tag)

| hardcase | count | % of 83 | notes |
|---|---:|---:|---|
| `multi_hop` | 73 | 88.0% | **dominant** — single-doc 안의 multi-section retrieval 어려움 |
| `distractor_heavy` | 31 | 37.3% | multi_hop 과 cross — distractor 가 evidence 위로 push |
| `long_context` | 7 | 8.4% | minority |
| `no_answer` | 1 | 1.2% | edge case |
| (no hardcase tag) | 6 | 7.2% | tag 외 패턴 — 후속 inspection 후보 |

multi-tag 합이 83 초과인 이유 — 73 multi_hop case 중 31개가 *동시에* distractor_heavy. 즉 가장 어려운 케이스 = **multi_hop AND distractor_heavy** (실제 단일 doc 안에서 여러 section 을 cross-reference 해야 하는데 distractor 가 ranking 을 흔드는 패턴).

### `expected_doc_ids` cardinality (개수)

| cardinality | count | notes |
|---|---:|---|
| 1 (single-doc expected) | 83 | 100% — multi-doc / comparison 패턴 0 |

본 83 case 는 *모두* 단일 doc 답변 기대. ADR 0059 의 `retrieval_miss` 정의 (`expected_doc_ids and not (expected_doc_ids & evidence_doc_ids)`) 이 multi-doc 패턴 (comparison query) 을 미스했다는 의미 아님 — 본 83 분포는 single-doc retrieval 의 ranking 문제가 dominant.

> **Update (2026-05-22, idx59/F2):** 위 인용한 `retrieval_miss` 정의 (`not (expected_doc_ids & evidence_doc_ids)`, bare intersection) 는 이후 `not expected_doc_ids.issubset(evidence_doc_ids)` 로 정정됨 ([failure_classifier.py](../../eval/scorers/failure_classifier.py) branch 3). bare-intersection 은 comparison `{A,B}` 에 evidence `{A}` (부분 커버리지) 를 retrieval_miss 로 잡지 못해 planner/unknown 으로 새던 버그였고, 이것이 본 표 "comparison 패턴 0" 의 직접 원인이었음. 정정 후 재측정 baseline 은 retrieval_miss 64→67. 본 문서 상단 수치 (n=83 등) 는 측정 HEAD (`a931a49`, 2026-05-19) 스냅샷으로 보존 — 이번 HEAD 기준 전면 재측정 재생성은 별도 follow-up issue 관할.

### `evidence_doc_ids` empty vs wrong

| pattern | count | % of 83 | 해석 |
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

## 범위 밖(Out-of-scope) (별 PR / 별 audit)

- 실제 retrieval fix (top_k bump / embedding swap / chunking 변경) — 본 audit 가 root cause 가설 ranking 만 emit; fix 는 가설별 별 PR.
- retrieval-eval skill Phase 4 (Metadata / filtering ablation) — sibling skill surface.
- Supply 3 — `failure-mode-harden-process` docs + regression test + ADR 0060.

## Verification

모든 인용 수치는 **committed, 재현 가능한 aggregate** 를 가리킨다 (gitignored `eval_summary.json` 직접 인용 아님 — 그 파일은 `.gitignore` `reports/real100/*` 로 fresh checkout 에 부재; issue #1243 정정).

- **Headline (정본):** `retrieval_miss = 64` 는 committed `reports/real100/baseline.aggregate.json::failure_category_counts.retrieval_miss == 64` + `reports/real100/failure_distribution.aggregate.json::failure_category_counts.retrieval_miss == 64` 로 검증 (2026-05-19 baseline run `de69c5c2`, n=221; 재생성: `scripts/render_failure_distribution.py`). 전체 180 failure 중 35.6% — `verifier_false_negative = 76` 이 더 큰 mode.
- **Per-case 슬라이스 (스냅샷):** 위 "데이터 inspection (n=83)" 의 slice 분포 (query_type / hardcase / expected-doc cardinality / evidence presence / 보조 신호) 는 committed `reports/real100/failure_slices.aggregate.json::categories.retrieval_miss` (`total == 83`) 에 카운트로 고정 — 이는 earlier `a931a49` run 스냅샷이며 정본 `de69c5c2` run 과 **다른 run** 이다 (재생성: `scripts/render_failure_slices.py`). 본문 표의 "evidence non-empty but wrong = 54" 는 retrieval_miss 정의상 expected ∉ evidence 이므로 artifact 의 `by_evidence_presence.non_empty == 54` 와 동치 (empty = 29). 정본 run 기준 슬라이스 재계산은 per-case `eval_summary.json` 이 필요해 별도 follow-up(real-eval run) 관할.
- 두 aggregate 모두 카운트/cardinality 만 담는다 — query/answer text, doc_id, chunk_id 는 ADR 0005 commit 경계를 넘지 않음. 분류 라벨은 ADR 0059 classifier (`eval/scorers/failure_classifier.py`) 출력.
- 원본 issue #1003 제목·이전 Verification 의 `83`·`84` 는 `a931a49` 스냅샷 run 의 headline 으로, 정본 baseline run(`de69c5c2`)의 `64` 로 정정됨 (#1245).
