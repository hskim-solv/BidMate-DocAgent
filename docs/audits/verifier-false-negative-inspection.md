# `verifier_false_negative = 76` 근본 원인(root-cause) inspection

| field | value |
|---|---|
| Issue | #1008 |
| Trigger PR | #1001 (ADR 0059 failure_classifier) + #1004 (supply 2 dashboard) |
| Source measurement | `reports/real100/eval_summary.json` regen at HEAD `a7fd711d` (post-#1001/#1004/#1005), n=221 |
| Date | 2026-05-19 |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 verifier fix 0건** (본 문서는 audit 만; 후속 issue 로 분기) |

> **Provenance (재현성 경계, #1237 정정)**: 본 문서의 headline `76` 과 모든 per-case slice 카운트(hardcase / evidence cardinality / expected-doc coverage / retry / specificity)는 HEAD `a7fd711d` 의 **비커밋 로컬 fresh real-eval run** 스냅샷이다 — gitignored `reports/real100/eval_summary.json::case_results[*]` (`.gitignore`) 의존이라 **fresh checkout 에서 재현 불가**. 재현 가능한 committed anchor 는 `reports/real100/failure_distribution.aggregate.json::failure_category_counts.verifier_false_negative` (HEAD 기준 **`49`**); `76` 은 아래 documented run-to-run variance band `49 ↔ 65 ↔ 76` 의 한 datapoint다. slice 카운트를 ADR 0005-safe committable artifact 로 만드는 작업은 follow-up #1239.

## 요약(Executive summary)

ADR 0059 (PR #1001) 가 정량화한 Phase 5 audit Finding #1 의 fresh remeasurement. PR #1001 측정 (65) / PR #1004 측정 (49) / 본 audit fresh (76) — run-to-run variance 크지만 ADR 0059 first-match contract `verifier_false_negative == abstention_outcomes.incorrect_answer` 매 run 유지 (76 == 76 ✓).

retrieval_miss=83 audit (#1005) 와 sibling — 본 문서는 **verifier layer 의 dominant failure**.

**카테고리 정의 (classifier semantics, #1237 정정)**: `verifier_false_negative` ⟺ `answerable=False AND abstained=False` (`eval/scorers/failure_classifier.py:110-115`) — gold 가 unanswerable 로 표시한 쿼리에 **모델이 답을 emit** 한 경우(over-answering / refuse 실패)다. verifier 가 evidence 를 sufficient 로 판정해 시스템이 답했으나 옳은 행동은 insufficient 판정 + abstain 이었다. 즉 "verifier 가 sufficient 근거를 거부" 가 *아니라* 그 반대 — **거부했어야 할 근거를 통과시킨 것**. (라벨명 `false_negative` 는 ADR 0059 가 고정한 키; 실제 동작은 위 정의를 따름.) 따라서 fix 축은 **abstention/refusal calibration** — unanswerable 쿼리에서 verifier 가 더 엄격히 insufficient 판정하도록 만드는 방향이다.

**핵심 발견 6개**:

1. **98.7% no_answer hardcase** — 76 case 중 75 가 `no_answer` tagged. unanswerable 쿼리에 답을 emit 한 over-answering(refuse 했어야 할 케이스)이 dominant failure.
2. **85.5% 구체성 keyword** — query 가 `얼마` / `구체적으로` / `기준은` / `몇 %` 등 specific value 요구. semantic intent: 단순 keyword match 가 아니라 정량 답 요구.
3. **82% multi-doc evidence** — verifier 가 evidence 받은 76 case 중 62 가 *여러 doc 의 chunk* 혼합. rule-based topic match 가 cross-doc 키워드 산재로 충족된 패턴.
4. **69.7% expected ∉ evidence** — 76 중 53 case 가 `expected_doc_ids ∉ evidence_doc_ids`. **단, unanswerable 쿼리이므로 "옳은 doc 검색 실패"(retrieval_miss)로 읽으면 안 됨** — 정답 행동은 abstain 이고 expected_doc_ids 는 distractor/참조용 신호다. failure 의 직접 원인은 evidence 가 비어있지 않은데도(아래 evidence cardinality 100% non-empty) abstain 하지 않고 답한 것.
5. **28.9% expected ∈ evidence** — 76 중 22 case 는 expected doc 가 evidence 에 포함됐는데도 verifier 가 sufficient 판정 → 답변 emit. unanswerable 쿼리이므로 doc 존재 여부와 무관하게 abstain 했어야 함 — topic/doc 매칭이 sufficiency 판정의 충분조건이 되는 게 문제(의미 검증 부재).
6. **80% retry=1** — verifier 가 retry 1회 trigger 했지만 fix 못함. retry 후에도 sufficient 판정.

## 데이터 inspection (n=76)

### `hardcase_categories` 별 slice

| hardcase | count | % of 76 | notes |
|---|---:|---:|---|
| `no_answer` | 75 | 98.7% | **dominant** — intentional unanswerable case 가 거의 전부 |
| `long_context` | 5 | 6.6% | no_answer 와 cross-tag |
| `distractor_heavy` | 4 | 5.3% | cross-tag |
| `multi_hop` | 2 | 2.6% | edge case |
| `ambiguous_query` | 1 | 1.3% | edge case |
| (no hardcase tag) | 1 | 1.3% | 1 case 만 untagged |

### `query_type` 별 slice

| query_type | count | % of 76 | notes |
|---|---:|---:|---|
| `abstention` | 76 | 100% | 단일 — YAML 의 `answerable=false` case 가 모두 이 카테고리 |

### evidence cardinality 별 slice

| evidence | count | % of 76 | 해석 |
|---|---:|---:|---|
| empty (0 docs) | 0 | 0% | retrieval 이 *항상* 무언가 가져옴. abstain 으로 fall through 안 함. |
| single-doc | 14 | 18.4% | minority — 단일 doc evidence 에서도 topic match |
| multi-doc | 62 | 81.6% | **dominant** — 여러 doc 의 chunk 혼합, topic 이 cross-doc 산재 |

### `expected_doc_ids` coverage 별 slice

> 주의: 전 케이스 `answerable=False`. 아래 expected vs evidence 비교는 retrieval 성공/실패 축이 *아니다* — unanswerable 쿼리의 정답 행동은 abstain 이며 expected_doc_ids 는 distractor/참조용. doc 존재 여부와 무관하게 abstain 했어야 함.

| 패턴 | count | % of 76 | 해석 |
|---|---:|---:|---|
| no expected (pure unanswerable) | 1 | 1.3% | edge case |
| expected ∈ evidence | 22 | 28.9% | expected doc 가 evidence 에 존재 — 그래도 abstain 이 정답. doc/topic 매칭이 sufficiency 충분조건화된 의미 검증 부재 |
| expected ∉ evidence | 53 | 69.7% | expected doc 부재 — unanswerable 라 "검색 실패"(retrieval_miss)로 오독 금지. evidence 가 비어있지 않은데 답한 게 failure |

### 보조 신호

| 측정 | 값 | 해석 |
|---|---:|---|
| `abstained=False` | 76 (100%) | 정의상 — verifier_false_negative = `answerable=False AND not abstained` (모델이 unanswerable 쿼리에 답 emit). `no_answer` 는 hardcase 태그로 별개 신호 — 98.7% 상관이나 동일 아님 |
| `term_match=False` | 76 (100%) | 답변 text 에 expected_term 부재 — 잘못된 답변 emit |
| `doc_match=False` | 76 (100%) | **`doc_match=False` ⟺ evidence 비어있지 않음**. unanswerable 분기(`eval/scorers/case.py:94` `doc_match = not evidence`)라 "expected doc 부재" 가 *아니라* 정반대 — evidence 가 존재. evidence cardinality 100% non-empty 와 정합 |
| `retry_count=1` | 61 (80.3%) | verifier 가 retry 1회 trigger — 그러나 retry 후에도 sufficient 판정 |
| `retry_count=0` | 14 (18.4%) | 첫 retrieval 만에 sufficient → no retry |
| `retry_count=2` | 1 (1.3%) | edge — retry 2 후에도 fail |

### Query specificity 패턴

쿼리 텍스트에 정량/구체성 키워드 포함 비율:

| pattern | match | 해석 |
|---|---:|---|
| `얼마` / `몇 ` / `몇%` / `%` | (subset of 65) | 정량 답 요구 |
| `구체적으로` / `구체적인` | (subset of 65) | 구체적 답 요구 |
| `기준은` / `?원` | (subset of 65) | 명시적 기준 요구 |
| **any specificity keyword** | **65 / 76 (85.5%)** | dominant — query 가 specific value 요구 |
| no specificity keyword | 11 / 76 (14.5%) | minority |

## Run-to-run 분산(variance) 분석

| 측정 이벤트 | run | verifier_false_negative count | contract status |
|---|---|---:|:---:|
| PR #1001 wire-up (HEAD `a931a49`) | initial | 65 | ✓ vs incorrect_answer=65 |
| PR #1004 supply 2 dashboard | midpoint | 49 | ✓ vs incorrect_answer=49 |
| 본 audit (HEAD `a7fd711d`) | fresh | **76** | ✓ vs incorrect_answer=76 |

ADR 0059 first-match contract (`verifier_false_negative == incorrect_answer`) 매 run 정합. 그러나 절대 count run-to-run variance 큼 (49 ↔ 65 ↔ 76).

**Variance source 가설**:
- retrieval ranking 의 tie-breaking 비결정성 (top_k 경계 score 동률)
- BGE-M3 (real production) vs hashing fallback 의 embedding 차이
- worktree 간 model cache state 차이
- (각 가설 검증은 본 audit out-of-scope — 별 issue 후보)

## 가설 ranking (post-inspection)

순위 = data 신호 강도 + fix 단순함 비례:

1. **[강 신호, fix 가능성 medium]** **Query specificity 기반 stricter sufficiency rule**.
   - Evidence: 85.5% query 가 정량/구체성 키워드 (`얼마`, `구체적으로`, `기준은`, `몇 %`). 현재 verifier 는 *topic match* 만 봄. specific value 요구 시 evidence 에 정량 phrase (숫자+단위) 있어야 sufficient.
   - Hypothesis: `verify_evidence` 의 stricter 분기 — query specificity classifier (regex) + evidence numeric/quantitative phrase 존재 요구.
   - Fix 후보 (별 PR): (a) `eval/scorers/case.py` 또는 `rag_verifier.py` 에 specificity classifier 도입 (~30 LOC, deterministic regex), (b) verify_evidence 가 query specificity TRUE 시 evidence 의 numeric/구체적 phrase 요구하는 추가 조건.

2. **[강 신호, fix 가능성 medium]** **Multi-doc topic spread 차단**.
   - Evidence: 82% case 가 multi-doc evidence. rule-based topic match 가 다른 doc 의 keyword 산재로 충족.
   - Hypothesis: `verify_evidence` 의 추가 조건 — topic 매칭은 *단일 doc 내* 에서 모두 충족되어야 sufficient (no cross-doc topic spread). 22 correct-doc cases 와의 누락 패턴 비교.
   - Fix 후보: per-doc topic match count 계산 후 `max(per_doc_match_count) >= ceil(len(topics) * 0.8)` 같은 strict 조건. ADR 0004 partial_topic_grounding 의 cross-doc 변형 후보.

3. **[중 신호, fix 가능성 high]** **No-answer linguistic anti-pattern detection**.
   - Hypothesis: query 가 `있나` / `있는가` / `존재하는가` / `명시되어` 같은 "존재 여부 묻기" pattern 일 때 evidence 가 *부정문 / 무존재 표현* 없으면 strict abstain.
   - Fix 후보: 30 LOC regex 추가. risk: 의도된 답변 케이스 false positive.

4. **[중 신호, fix 가능성 low]** **doc 존재가 sufficiency 충분조건화 — 22 case** (expected doc 가 evidence 에 있어도 unanswerable 라 abstain 했어야).
   - Hypothesis: verifier 가 wrong section 의 topic 으로 sufficient 판정. 즉 *doc-level* 매칭은 OK 인데 *section-level* 로 질문에 답하는 내용이 없는 케이스 — unanswerable 쿼리에서 doc/topic 존재만으로 sufficient 판정하면 안 됨.
   - Fix 후보: chunk-level claim alignment check. 큰 surface 변경, ADR worthy.

5. **[약 신호]** **Retry strategy 무효** (80% retry=1 but still miss).
   - 가설 4 (retrieval_miss audit) 의 sibling — retry 가 verifier-only loop. retrieval refinement 동반 안 됨.
   - Fix 후보: ADR 0004 retry policy 확장 (Track C audit 의 가설 4 와 동일).

6. **[측정 surface gap]** **Run-to-run variance 자체가 audit 대상**.
   - 49 ↔ 65 ↔ 76 variance 의 source 진단 — retrieval ranking tie-breaking? embedding state? cache?
   - Fix 후보: variance source 진단 audit (별 issue) — 매 measurement 마다 seed/cache 명시 + variance bound 측정.

## 후속 issue 후보

| 후보 | scope | priority |
|---|---|:---:|
| Issue F — Query specificity classifier + verify_evidence stricter rule (가설 1) | ~80 LOC + ADR 0061 + 측정 검증 | high |
| Issue G — Multi-doc topic spread 차단 (가설 2) | ~50 LOC + 측정 검증, ADR 0004 augment 후보 | high |
| Issue H — No-answer linguistic anti-pattern (가설 3) | ~30 LOC regex + 측정 검증 | medium |
| Issue I — Chunk-level alignment check (가설 4) | ~150 LOC + ADR + 큰 surface 변경 | medium |
| Issue J — Variance source 진단 audit (가설 6) | ~100 LOC measurement runner + audit doc | medium |
| Issue K — Retrieval refinement on verifier retry (가설 5) | ADR 0004 retry policy 확장 — Track C audit 의 sibling | low |

## 범위 밖(Out-of-scope) (별 PR / 별 audit)

- 실제 verifier fix (위 6 가설 중 어느 하나) — 본 audit 가 가설 ranking 만 emit; fix 는 가설별 별 PR.
- retrieval_miss=83 의 fix (#1005 의 후속 Issue A-E) — sibling failure surface.
- ADR 0058 hybrid switch 의 verifier 영향 분리 측정 — 별 ablation.
- Supply 3 — `failure-mode-harden-process` + ADR 0060.

## Verification

- **재현 가능한 committed anchor**: `reports/real100/failure_distribution.aggregate.json::failure_category_counts.verifier_false_negative` (HEAD 기준 **`49`**, `scripts/render_failure_distribution.py` 로 재생성 — ADR 0005-safe aggregate). 동 파일 `finding_1_contract.match == true` (`verifier_false_negative == abstention_outcomes.incorrect_answer`)로 ADR 0059 first-match contract 검증.
- **headline `76` 은 비커밋 로컬 datapoint**: post-#1001/#1004 fresh real-eval at HEAD `a7fd711d` 의 gitignored `reports/real100/eval_summary.json` 에서 측정 — fresh checkout 에 없으므로 **재현 불가**. 위 committed anchor(`49`)와의 차이는 documented run-to-run variance band `49 ↔ 65 ↔ 76` 의 한 점으로, 비커밋 measurement 임을 본 문서 상단 Provenance 배너에 명시.
- **slice 분포(hardcase / evidence cardinality / expected-doc coverage / retry / specificity)** 는 동일 비커밋 run 의 `case_results[*]` (`failure_category == "verifier_false_negative"`) 필드에서 카운트 추출 (LOC 카운트 형식, per-case text 미노출 — ADR 0005 경계 준수) — 그러나 committed artifact 부재라 **현재 재현 불가**. `render_failure_distribution.py` 가 이 slice 카운트를 committable aggregate 로 emit 하도록 확장하는 작업은 follow-up #1239.
- Run-to-run variance (49 ↔ 65 ↔ 76) 은 3 measurement 의 raw output 비교 — 모두 동일 HEAD 가 아니지만 ADR 0059 contract 는 매 run 유지.
