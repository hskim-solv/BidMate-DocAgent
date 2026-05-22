# `retrieval_miss = 67` 근본 원인(root-cause) inspection

> **Regen (2026-05-22, #1277).** 본 문서는 #1276 (ADR 0059 `classify_failure`
> taxonomy 3-bug fix) + #1287 (committed baseline regen, #1321) 이후의 정본
> baseline (`reports/real100/baseline.aggregate.json`, n=221) 기준으로 전면
> 재생성됐다. 이전 판은 earlier run (`a931a49`, 2026-05-19) 의 `retrieval_miss = 83`
> 스냅샷이었다 — 그 측정은 다른 HEAD/run 이라 보존된 cross-HEAD 기록일 뿐
> 정본이 아니다 ([variance-source-inspection.md](variance-source-inspection.md) 의
> "variance 는 cross-HEAD 일 뿐 run-to-run 아님" 결론 참조). F2 정정 (bare-intersection
> → `issubset`, 아래 cardinality 표 노트) 으로 `retrieval_miss` 가 64→67 로 재분포됐다.

| field | value |
|---|---|
| Issue | #1277 (재생성) ← #1003 (원본 audit) |
| Trigger PR | #1276 (ADR 0059 `classify_failure` 3-bug fix, closes #1275) + #1287 (baseline regen, #1321) |
| Source measurement | committed `reports/real100/baseline.aggregate.json` / `failure_distribution.aggregate.json` / `failure_slices.aggregate.json` (n=221) |
| Date | 2026-05-22 |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 retrieval fix 0건** (본 문서는 audit 만; 후속 issue 로 분기) |

## 요약(Executive summary)

ADR 0059 7-category 분류기 (`eval/scorers/failure_classifier.py`, PR #1001) 가
n=221 real-eval 에서 **`retrieval_miss = 67`** 측정 (전체 180 failure 의 37.2%) — 여전히
`verifier_false_negative = 76` (42.2%) 다음의 두 번째 *dominant failure mode*. failure
RATE 로는 67/221 = **0.303** (`tests/test_failure_rate_regression.py` ceiling 0.34 아래).

분류 표면 부재 (audit 시점) 일 때는 보이지 않던 신호 — 본 audit 의 **부산물**:
"측정 표면이 생기자마자 audit 가 모르던 더 큰 함정이 노출됨" (ADR 0054 → 0056 cascade 와
동일 구조).

**핵심 발견 5개** (raw inspection 결과로 ranking 확정):

1. **86.6% multi_hop hardcase** — `retrieval_miss=67` 중 58 case 가 `multi_hop` tagged.
   본질적으로 *단일 doc 내 multi-section reasoning* 패턴이 dominant root cause.
2. **97.0% single_doc query_type** — query_type 측면에서는 단일 doc 질의(65 case),
   그러나 hardcase tag 는 multi_hop — *intent 는 single doc, evidence 는 multi-section*.
3. **61.2% has non-empty evidence (wrong doc)** — retrieval 자체는 결과 가져오는 데
   성공(41 case), *ranking* 이 expected doc 을 top-4 밖으로 밀어냄. embedding / scoring 문제.
4. **38.8% has empty evidence** — 완전 0 결과(26 case). ADR 0058 hybrid 후에도 expected
   doc 가 top-4 에 못 들어오는 *hard miss* 케이스. embedding mismatch 또는 chunking 가설.
5. **multi-doc-expected 패턴 비-0 (1 case)** — F2 정정(`issubset`) 후, expected
   cardinality 2 의 부분-커버리지 case 1개가 `retrieval_miss` 로 올바로 분류됨 (bare-intersection
   공식에서는 planner/unknown 으로 새던 케이스). 아래 cardinality 표 참조.

## 데이터 inspection (n=67)

### `query_type` 별 slice

| query_type | count | % of 67 | notes |
|---|---:|---:|---|
| `single_doc` | 65 | 97.0% | dominant — single-doc intent 가 fail 의 거의 전부 |
| `follow_up` | 2 | 3.0% | marginal |

> F2 정정 전 판에서는 `abstention` query_type 1 case 가 retrieval_miss 에 포함됐으나,
> 정정 후 분포(현 baseline)에서는 abstention case 가 `verifier_false_negative` / `unknown`
> 으로 이동해 retrieval_miss query_type 은 single_doc + follow_up 만 남는다.

### `hardcase_categories` 별 slice (multi-tag)

| hardcase | count | % of 67 | notes |
|---|---:|---:|---|
| `multi_hop` | 58 | 86.6% | **dominant** — single-doc 안의 multi-section retrieval 어려움 |
| `distractor_heavy` | 21 | 31.3% | multi_hop 과 cross — distractor 가 evidence 위로 push |
| `long_context` | 4 | 6.0% | minority |
| `ambiguous_query` | 1 | 1.5% | edge case |
| (no hardcase tag) | 6 | 9.0% | tag 외 패턴 — 후속 inspection 후보 |

multi-tag 합이 67 초과인 이유 — 58 multi_hop case 중 **18개가 *동시에* distractor_heavy**
(multi_hop 단독 40 case). 즉 가장 어려운 케이스 = **multi_hop AND distractor_heavy** (실제
단일 doc 안에서 여러 section 을 cross-reference 해야 하는데 distractor 가 ranking 을 흔드는 패턴).

### `expected_doc_ids` cardinality (개수)

| cardinality | count | notes |
|---|---:|---|
| 1 (single-doc expected) | 66 | 단일 doc 답변 기대 — ranking 문제가 dominant |
| 2 (multi-doc expected) | 1 | 부분-커버리지 miss — F2 정정으로 비로소 retrieval_miss 로 분류 |

> **F2 정정 노트 (#1276 branch 3).** 이전 `retrieval_miss` 정의는 bare intersection
> (`not (expected_doc_ids & evidence_doc_ids)`) 으로, comparison/multi-doc `{A,B}` 에
> evidence `{A}` (부분 커버리지) 를 retrieval_miss 로 잡지 못해 planner/unknown 으로 새는
> 버그였다. 이것이 이전 판 cardinality 표의 "comparison 패턴 0" 의 직접 원인이었다.
> 현재 정의는 `not expected_doc_ids.issubset(evidence_doc_ids)` ([failure_classifier.py](../../eval/scorers/failure_classifier.py)
> branch 3, case.py:80 `doc_match` 와 동치) 이며, cardinality 2 의 부분-커버리지 case
> 1개가 이제 retrieval_miss 에 올바로 포함된다. (이 1 case 의 base query_type 은 single_doc,
> hardcase 무태그 — comparison query_type 자체는 아니지만, multi-doc-expected 패턴이 더 이상
> 0 이 아님을 확인.) 정정 후 baseline 은 retrieval_miss 64→67.

### `evidence_doc_ids` empty vs wrong

| pattern | count | % of 67 | 해석 |
|---|---:|---:|---|
| evidence non-empty but wrong | 41 | 61.2% | **dominant** — retrieval API 가 *결과 가져옴*, ranking 이 expected 를 top-4 밖으로 push. embedding / scoring 문제. |
| evidence empty (0 docs) | 26 | 38.8% | hard miss — ADR 0058 hybrid 도 expected doc 을 top-4 에 못 올림. chunking / embedding mismatch 가설. |

### 보조 신호

| 측정 | 값 | 해석 |
|---|---:|---|
| `abstained=True` | 31 (46.3%) | verifier 가 잘못된 retrieval 을 catch + abstain. 약 절반은 catch, 절반은 답변 시도. |
| `term_match=True` | 7 (10.4%) | wrong doc 이 우연히 expected term 포함 — minority. |
| `doc_match=False` | 67 (100.0%) | retrieval_miss 정의상 expected 가 evidence 에 부재(혹은 부분 커버리지). integrity check. |
| `retry_count=1` | 48 (71.6%) | verifier retry 1번 trigger 됐지만 fix 못함 — retry strategy 가 retrieval miss 에는 무효. |

## 가설 ranking (post-inspection)

순위 = data 신호 강도 + fix 단순함 비례:

1. **[강 신호, fix 가능성 medium]** **단일 doc 내 multi-section retrieval — chunking + ranking 한계**.
   - Evidence: 86.6% multi_hop tag + 97.0% single_doc query_type + 61.2% wrong doc retrieved.
   - Hypothesis: 단일 doc 의 답이 *여러 section 에 분산* 되어 있어 top-4 (ADR 0001 baseline) 가 충분치 못함.
   - Fix 후보: (a) `top_k` 8 또는 12 로 확장 후 measure, (b) parent-section reassembly 강화 (rag_retrieval.py existing surface), (c) per-doc multi-chunk gather (retrieval mode = "section-aware").
2. **[중 신호, fix 가능성 high]** **Distractor pressure on multi_hop** (31% cross-tag).
   - Hypothesis: multi_hop 단독 (40 case) vs multi_hop+distractor (18 case) 의 retrieval 실패율 비교 → distractor 가 ranking 흔드는 영향 분리.
   - Fix 후보: cross-encoder reranker (현재 ADR 0026 stub) 의 real backend 활성화 후 distractor 압박 받는 multi_hop 만 ablation.
3. **[중 신호, fix 가능성 low]** **38.8% empty evidence — hard miss**.
   - Hypothesis: expected doc 가 hybrid retrieval 도 못 surface(26 case). embedding mismatch (도메인 specificity 부족) 또는 chunking artifact (expected_terms 가 chunk 경계로 분할).
   - Fix 후보: (a) 26 empty case 의 expected doc 에 대해 oracle retrieval (직접 doc_id 로 fetch) 후 query↔doc similarity 직접 측정, (b) chunking strategy ablation.
4. **[약 신호]** **Verifier retry 무효** (71.6% retry=1 but still miss).
   - Verifier retry 가 retrieval 결과를 *변경 가능하게* 하지 않음 — retry 는 verifier-only loop, retrieval 결과는 그대로. 본 분류기는 retry 후 final result 기준 분류.
   - Fix 후보: retry 가 retrieval refinement 도 trigger 하게 변경 (ADR 0004 retry policy 확장) — 큰 surface 변경.

## 후속 issue 후보

| 후보 | scope | priority |
|---|---|:---:|
| Issue A — `top_k` 8 vs 4 ablation (가설 1) | retrieval-eval skill Phase 4 candidate; ~150 LOC ablation runner + REPORT.md | high |
| Issue B — multi_hop+distractor isolation measurement (가설 2) | 18 cross-tagged case 만 isolate 한 sub-eval; ~80 LOC | medium |
| Issue C — Cross-encoder reranker real backend (가설 2) | ADR 0026 re-open conditions 검증; 별 ADR 후보 | medium |
| Issue D — 26 empty-evidence case 의 oracle retrieval analysis (가설 3) | per-case query↔doc cosine inspection; ~100 LOC + audit doc | medium |
| Issue E — ADR 0004 retry policy 확장 (가설 4) | retry 가 retrieval refinement 도 trigger; production code 변경 + ADR | low |

## 범위 밖(Out-of-scope) (별 PR / 별 audit)

- 실제 retrieval fix (top_k bump / embedding swap / chunking 변경) — 본 audit 가 root cause 가설 ranking 만 emit; fix 는 가설별 별 PR.
- retrieval-eval skill Phase 4 (Metadata / filtering ablation) — sibling skill surface.

## Verification

모든 인용 수치는 **committed, 재현 가능한 aggregate** 를 가리킨다 (gitignored `eval_summary.json`
직접 인용 아님 — 그 파일은 `.gitignore` `reports/real100/*` 로 fresh checkout 에 부재; issue #1243 정정).

- 본 audit 가 인용하는 headline `retrieval_miss = 67` 은 committed `reports/real100/failure_distribution.aggregate.json::failure_category_counts.retrieval_miss == 67` (= `baseline.aggregate.json` 동일값) 으로 검증 (재생성: `scripts/render_failure_distribution.py`). failure RATE 67/221 = 0.303 < `tests/test_failure_rate_regression.py` ceiling 0.34.
- 각 slice 분포 (query_type / hardcase / expected-doc cardinality / evidence presence / 보조 신호) 는 committed `reports/real100/failure_slices.aggregate.json::categories.retrieval_miss` 에 카운트로 고정 (재생성: `scripts/render_failure_slices.py`). 본문 표의 "evidence non-empty but wrong = 41" 은 artifact 의 `by_evidence_presence.non_empty == 41` 과 동치 (empty = 26). cross-tab "multi_hop AND distractor_heavy = 18" 은 `by_hardcase` 의 multi_hop(58) + distractor_heavy(21) 중첩으로, 별도 counts-only 도출 (ADR 0005 경계 내).
- 두 aggregate 모두 카운트/cardinality 만 담는다 — query/answer text, doc_id, chunk_id 는 ADR 0005 commit 경계를 넘지 않음 (`scripts/_governance.py::find_eval_private_text` `{}` 확인). 분류 라벨은 ADR 0059 classifier (`eval/scorers/failure_classifier.py`) 출력.
- 위 수치는 #1276/#1287 (#1321) 정정 후 정본 baseline (n=221) snapshot 이며, 차기 local real-eval 시 위 두 스크립트로 재생성된다. 이전 판의 `retrieval_miss = 83` (Verification `== 84`) 는 earlier run (`a931a49`) 의 cross-HEAD 값으로, 정본 baseline 의 67 로 정정됨.
