# `verifier_false_negative = 76` 근본 원인(root-cause) inspection

> **Reconcile (2026-05-22, #1277).** #1276 (ADR 0059 `classify_failure` 3-bug fix) +
> #1287 (committed baseline regen, #1321) 이후 정본 baseline 기준으로 재확인했다.
> `verifier_false_negative` 는 분류기 정정에 **불변(76)** — first-match-wins 순서상 다른
> 카테고리 fix (vfp 3→0, retrieval_miss 64→67, planner 1→3, unknown 35→33) 보다 앞서므로
> 본 문서의 모든 slice (hardcase 75/5/4/2/1/1 · query_type 76 · evidence 14/62 ·
> expected-coverage 1/22/53 · retry 61/14/1 · specificity 65) 는 정정 후 baseline 에서도
> byte-identical 재현됐다. retrieval_miss 를 가리키던 cross-pointer 2곳 (아래 본문/Out-of-scope)
> 만 83→67 로 갱신했다.

| field | value |
|---|---|
| Issue | #1008 (원본 audit) → #1277 (재확인) |
| Trigger PR | #1001 (ADR 0059 failure_classifier) + #1004 (supply 2 dashboard) + #1276/#1287 (분류기 fix + baseline regen) |
| Source measurement | committed `reports/real100/baseline.aggregate.json` / `failure_distribution.aggregate.json` / `failure_slices.aggregate.json` (n=221) |
| Date | 2026-05-19 (측정) · 2026-05-22 (재확인) |
| Author | Hyunsoo Kim |
| Strict-forbid | **실 verifier fix 0건** (본 문서는 audit 만; 후속 issue 로 분기) |

## 요약(Executive summary)

ADR 0059 (PR #1001) 가 정량화한 Phase 5 audit Finding #1 의 fresh remeasurement. PR #1001 측정 (65) / PR #1004 측정 (49) / 본 audit fresh (76) — run-to-run variance 크지만 ADR 0059 first-match contract `verifier_false_negative == abstention_outcomes.incorrect_answer` 매 run 유지 (76 == 76 ✓).

retrieval_miss=67 audit ([retrieval-miss-inspection.md](retrieval-miss-inspection.md), #1277) 와 sibling — 본 문서는 **verifier layer 의 dominant failure**.

**핵심 발견 6개**:

1. **98.7% no_answer hardcase** — 76 case 중 75 가 `no_answer` tagged. 정확히 verifier 의 unanswerable 판정 실패가 dominant failure.
2. **85.5% 구체성 keyword** — query 가 `얼마` / `구체적으로` / `기준은` / `몇 %` 등 specific value 요구. semantic intent: 단순 keyword match 가 아니라 정량 답 요구.
3. **82% multi-doc evidence** — verifier 가 evidence 받은 76 case 중 62 가 *여러 doc 의 chunk* 혼합. rule-based topic match 가 cross-doc 키워드 산재로 충족된 패턴.
4. **70% wrong expected doc** — 76 중 53 case 가 expected doc 을 retrieval 도 못 가져옴 (`expected_doc_ids ∉ evidence_doc_ids`). 이는 retrieval_miss audit (#1005) 와의 cross-failure.
5. **30% correct doc but verifier still fails** — 76 중 22 case 는 expected doc 가 evidence 에 있는데도 verifier 가 sufficient → 답변 emit. doc 매칭만으론 부족, *답이 실제로 doc 안에 있는지* 의 의미 검증 부재.
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

| 패턴 | count | % of 76 | 해석 |
|---|---:|---:|---|
| no expected (pure unanswerable) | 1 | 1.3% | edge case |
| expected ∈ evidence (correct doc retrieved) | 22 | 28.9% | **retrieval 성공인데도 verifier 실패** — 의미 검증 부재 |
| expected ∉ evidence (wrong doc retrieved) | 53 | 69.7% | retrieval_miss + verifier_false_negative 의 cross-failure |

### 보조 신호

| 측정 | 값 | 해석 |
|---|---:|---|
| `abstained=False` | 76 (100%) | 정의상 — verifier_false_negative = no_answer AND not abstained |
| `term_match=False` | 76 (100%) | 답변 text 에 expected_term 부재 — 잘못된 답변 emit |
| `doc_match=False` | 76 (100%) | expected doc 가 evidence 에 부재 (또는 expected 미정) |
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

4. **[중 신호, fix 가능성 low]** **Retrieval-miss cross-failure 22 case** (correct doc 가 evidence 에 있는데도 verifier 실패).
   - Hypothesis: retrieval 은 성공인데 verifier 가 wrong section 의 topic 으로 sufficient 판정. 즉 *doc-level* 매칭은 OK 인데 *section-level* 답이 없는 케이스.
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
- retrieval_miss=67 의 fix (#1277 의 후속 Issue A-E) — sibling failure surface.
- ADR 0058 hybrid switch 의 verifier 영향 분리 측정 — 별 ablation.
- Supply 3 — `failure-mode-harden-process` + ADR 0060.

## Verification

모든 인용 수치는 **committed, 재현 가능한 aggregate** 를 가리킨다 (gitignored `eval_summary.json`
직접 인용 아님 — issue #1243 정정).

- 본 audit 가 인용하는 76 은 committed `reports/real100/failure_distribution.aggregate.json::failure_category_counts.verifier_false_negative == 76` (= `baseline.aggregate.json` 동일값) 으로 검증. ADR 0059 first-match contract `verifier_false_negative == abstention_outcomes.incorrect_answer == 76` 는 `finding_1_contract.match == true` 로 고정.
- 각 slice 분포 (hardcase / query_type / evidence presence / expected cardinality / 보조 신호) 는 committed `reports/real100/failure_slices.aggregate.json::categories.verifier_false_negative` 에 카운트로 고정 (재생성: `scripts/render_failure_slices.py`). 본문의 finer slice (evidence distinct-doc 14/62 · expected-coverage 1/22/53 · specificity 65) 는 동일 case 집합에서 도출한 counts-only 값으로, ADR 0005 경계 내 (`scripts/_governance.py::find_eval_private_text` `{}` 확인) — query/answer text, doc_id, chunk_id 비노출.
- Run-to-run variance (49 ↔ 65 ↔ 76) 은 서로 다른 HEAD 의 measurement 비교 — [variance-source-inspection.md](variance-source-inspection.md) 가 *cross-HEAD* 차이임을 확정 (same-HEAD spread=0). ADR 0059 contract 는 매 run 유지하며, #1276/#1287 정정 후 정본 baseline 에서도 vfn=76 불변.
