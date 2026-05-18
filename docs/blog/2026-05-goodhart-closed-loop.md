# 측정 도구가 자기 함정을 발견했을 때 — 5-step closed loop

> 이 글은 5 PR / 3 ADR / 2 audit 의 closed measurement loop 를 문서화한다.
> 처음 PR (#946) 이 측정 도구를 도입했고, 두 번째 PR (#959) 이 그 도구가
> 자기 자신의 metric 정의에 vacuous-truth 함정을 가지고 있다는 것을 발견했고,
> 세 번째 cluster (#961 + #963) 가 측정 표면의 다른 갭들을 audit 했고,
> 네 번째 cluster (#965 + #968) 가 통계 정직성을 PR 게이트로 박았고,
> 다섯 번째 (#987) 가 process rationality 측정 표면을 새로 도입했다.
>
> Sibling posts:
> [`hyde-measurement-saturation.md`](./hyde-measurement-saturation.md),
> [`2026-05-extractive-baseline.md`](./2026-05-extractive-baseline.md).

이 closed loop 의 가장 큰 lesson 은 — *측정 도구의 첫 측정 결과를 신뢰하지 않는 것* 이다. 직관에 반하는 결과 (random baseline 이 default 보다 *높은* score) 가 나왔을 때, "시스템이 random 보다 못한가?" 가 아니라 "metric 정의 자체가 깨졌나?" 로 시작하는 것. 본 글의 5 step 은 그 한 질문에서 파생된 cascade 다.

## Step 1 — 측정 도구 도입 (PR #946)

[ADR 0053](../adr/0053-distinguishing-power-floor-ablations.md) 가 "distinguishing power gauge" 를 도입했다. 핵심 질문: *retrieval 이 진짜로 도움이 되는가?* 를 falsify 하기 위해 두 가지 floor backend 를 정의:

- `random_retrieval` — SHA-256(query) deterministic 해시로 chunk 무작위 선택 (no embedding, no relevance signal)
- `single_chunk` — top_k=1, no rerank, no retry

각 metric 의 `(default - floor) / (1 - floor)` 가 `signal_alive`. 의미: "default 가 random 보다 의미있게 위에 있는가?".

`scripts/distinguishing_power.py` 가 measurement 한 결과 (n=221, real-eval surface):

| metric | default (full) | random_retrieval | gap | signal_alive |
|---|---:|---:|---:|:---:|
| accuracy | 29.66% | 2.54% | **+27.12pp** | ✓ |
| claim_citation_alignment | 96.28% | 88.24% | **+8.04pp** | ✓ |
| groundedness | 25.34% | 36.20% | **−10.86pp** | ❌ |
| citation_precision | 19.02% | 34.84% | **−15.82pp** | ❌ |
| answer_format_compliance | 20.81% | 44.80% | **−23.98pp** | ❌ |

5 metric 중 **3개에서 random 이 default 보다 높은 score**. 직관에 명백히 반함 — 정말로 random retrieval 이 정답에 더 가까운 evidence 를 retrieved 하고 있을 수 있나?

여기서 둘 중 하나를 선택해야 한다. (a) 시스템이 진짜로 random 보다 못하니까 retrieval / verifier / generator 를 갈아엎자, 또는 (b) metric 정의 자체가 깨졌나 의심하자.

(a) 가 *6개월짜리* 작업이고 (b) 가 *2주짜리* 작업이라는 점에서, 우선순위가 명백했다. 하지만 그것보다 더 중요한 건 — **(b) 가 falsifiable** 했다. metric 정의의 corner case 를 grep 하면 binary 답이 나온다.

## Step 2 — Goodhart 함정 발견 + scorer semantics fix (PR #959)

[ADR 0054](../adr/0054-conditional-on-answer-scorer-semantics.md) 가 fix 한 함정. `eval/scorers/case.py:79-92` 를 grep:

```python
if answerable:
    doc_match = expected_doc_ids.issubset(evidence_doc_ids)
    term_match = contains_all_terms(combined_text, expected_terms)
    accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
    groundedness = 1.0 if term_match and evidence and not abstained else 0.0
    citation_precision = citation_doc_precision if citation_term_match else 0.0
    abstention = None
else:
    doc_match = not evidence
    term_match = abstained
    accuracy = None
    groundedness = 1.0 if abstained and not evidence else 0.0   # ← 함정 (vacuous truth)
    citation_precision = 1.0 if abstained and not evidence else 0.0  # ← 함정
    abstention = 1.0 if abstained else 0.0
```

문제의 라인: `answerable=False AND abstained=True AND not evidence` 분기에서 `groundedness = citation_precision = 1.0`. *답이 없는 질문에 답을 안 했고 evidence 도 안 가져왔다* 는 vacuous-truth — true 지만 *quality 신호가 아니다*.

`random_retrieval` 의 `abstention_rate ≈ 89%` 가 핵심. random 이 검색한 chunk 들은 대부분 query 와 무관 → verifier (`rag_verifier.py`) 가 reject → abstain. **abstain 한 케이스가 모두 `groundedness = 1.0` 을 받음** → mean inflate.

같은 신호가 다른 곳에서 *별도로* 측정되고 있었다는 것이 더 중요한 발견이었다. PR #464 가 도입한 `abstention_outcomes` 3-bin (`correct_refusal` / `incorrect_answer` / `boundary_partial`) 이 refusal 정확성을 *이미* 측정 중. 그러므로 quality metric 의 vacuous 1.0 은 **double-count**.

### Fix

`groundedness` / `citation_precision` / `answer_format_compliance` 의 의미를 "substantive answer 시도 (`answerable=True AND not abstained`)" 에 한정. 비-substantive 케이스 (`correct_refusal`, `incorrect_answer`, `boundary_partial`) 는 `None` → mean 분모 제외.

`[ALLOW_REGRESSION: ADR 0054 metric-semantics shift]` 게이트로 baseline regen, 5/5 metric 양수 gap 회복.

### 일반화 lesson

함정 발견에는 *두 번째 측정 surface* 가 필요했다. 단일 metric (accuracy) 만 봤으면 "+27pp" 통과시켰을 거. distinguishing-power gauge (Step 1) 가 함정 차단의 trigger. 이게 ADR 0053 의 진짜 가치 — gauge 자체가 의미있는 게 아니라, *다른 measurement 의 sanity check 로서의 gauge 가* 의미.

## Step 3 — 측정 표면 audit (PR #961 + #963)

scorer fix 후, 다음 질문은 "*이런 함정이 다른 곳에 또 있나?*" 였다. 그래서 [`eval-framework-progressive-audit` 스킬](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889) 의 5-phase 진행.

### Phase 3 audit — process + trajectory observability ([#961](../audits/eval-framework-phase3-audit.md))

4-item 진단 결과:

| # | item | 상태 |
|---|---|:---:|
| 1 | per-query 로깅 (latency / call count / token / cost) | ◐ partial |
| 2 | trajectory 직렬화 (모든 LLM call I/O) | ◐ partial |
| 3 | trajectory-rationality rubric (LLM-as-judge) | ✗ absent |
| 4 | pareto reporting (quality vs cost 2D plot) | ◐ partial |

가장 큰 갭: **item 3 (rationality rubric 0건)**. 기존 3 LLM-judge gate (real-data quality / synthetic quality / RAGAS) 모두 *answer correctness* 만 채점. **process rationality** (planner 가 합리적으로 decompose 했나, retrieval retry 가 evidence-driven 인가, synthesis 가 evidence 와 일관한가) 측정 표면 0차원.

### Phase 4 audit — statistical rigor ([#963](../audits/eval-framework-phase4-audit.md))

3-item 진단:

| # | item | 상태 |
|---|---|:---:|
| 1 | Multi-seed 운영 (variant 별 3 seed mean ± std) | ◐ partial |
| 2 | Paired bootstrap CI 운영 | ✓ present |
| 3 | `claim_validator.py` 부재 — 개선 주장 자동 검증기 | ✗ absent |

가장 큰 갭: **item 3 (claim_validator 0건)**. PR body 의 "+X.Xpp SIG/NS" 표기 convention 운영 중이지만 paired CI 부호 확인 + SIG/NS 라벨 부여를 작성자 손으로 — 자동 게이트 부재. 25 PR/주 빈도에서 spot check 의존.

audit 의 핵심 패턴 — *audit 자체가 코드 추가 0건*. 스킬 본문이 "strictly forbid: 실제 구현 / 로깅 추가 0건". audit 는 진단 + supply 제안만; 실제 fix 는 별 PR. 이게 *audit 의 결정 깊이를 보장* — audit 가 implementation 와 섞이면 진단의 객관성이 손상됨.

## Step 4 — 자동 게이트 도입 (PR #965 ADR 0055 + PR #968 trace v2)

Phase 4 item 3 supply: [ADR 0055 — `claim_validator` as PR gate](../adr/0055-claim-validator-as-pr-gate.md).

### `Claim:` convention

PR body 에 다음 한 줄을 *옵션* 으로 도입:

```
Claim: <metric>=<+X.Xpp>     # 예: Claim: accuracy=+4.0pp
```

명시 시 `scripts/validate_claim.py` 가 paired bootstrap CI 자동 검증. 4 조건 모두 통과해야 PASS:

1. CI 가 0을 가로지르지 않음 (`ci_lo` 와 `ci_hi` 부호 동일)
2. effective sample size (post-None-skip, ADR 0054 substantive-only) ≥ `--min-sample` (default 200)
3. `sign(claim) == sign(mean_diff)` (방향 일치)
4. `|claim| ≤ |optimistic CI edge|` (over-claim 차단; positive claim 은 `ci_hi`, negative 는 `ci_lo`)

`pr-eval.yml` 신규 step `Validate improvement claims` — `if: contains(github.event.pull_request.body, 'Claim:')` 조건부. `Claim:` 미명시 PR 0 영향 — 기존 PR 패턴 backward-compatible (검증: `gh pr list --state merged --limit 100` regex 매칭 0건).

### ALLOW_OVERCLAIM 의도적 미도입

ADR 0050 / ADR 0054 가 의도적 regression 의 `[ALLOW_REGRESSION]` escape 를 도입했다. ADR 0055 의 *대칭 반대* — improvement claim 의 escape (`ALLOW_OVERCLAIM`) 는 의도적 미도입. 이유:

- ALLOW_REGRESSION 의 사용 케이스 = corpus 확장 (ADR 0052) 또는 scorer semantics 변경 (ADR 0054) — *측정 표면 자체* 가 변경되는 경우. 절대값 회귀가 의미가 없음 (비교 가능성 reset).
- ALLOW_OVERCLAIM 의 정당화 가능 케이스 부재. "이번 claim 은 over 인 거 알지만 narrative 상 +5pp 라고 쓰고 싶다" 는 정직성 위반.
- 비대칭이 옳은 이유 = *escape 의 비용 비대칭*. ALLOW_REGRESSION 은 baseline 1회 reset 비용, ALLOW_OVERCLAIM 은 portfolio claim 의 신뢰 영구 손실.

### Trace schema v2 (PR #968, issue #967)

`TRACE_SCHEMA_VERSION` 1→2. `prediction["trace"]` dict 에 `synthesis_llm_call` 키 추가 — `BIDMATE_TRACE_FULL=1` env-gated 로 anthropic / openai_compatible synthesis backend 가 `user_prompt_text + completion_text` 채움. ADR 미발행 (env-gated, default off → ADR 0001 byte-identical 합성 baseline 영향 0).

Phase 3 item 2 supply. 이 자료가 Step 5 의 input 이 됨.

## Step 5 — Process rationality 측정 표면 도입 (PR #987)

Phase 3 item 3 supply: [ADR 0056 — rationality_judge measurement surface](../adr/0056-rationality-judge-measurement-surface.md).

### 3-axis judge

신규 `eval/judges/rationality_judge.py` — Gate 3 RAGAS (`eval/judges/llm_judge.py:judge_ragas`) 와 동일 contract `judge_rationality(summary, *, backend, traces_dir, cache_dir, token_budget) -> (local_payload, aggregate)`.

3 axes, 각 `[0.0, 1.0]`:

| axis | input source |
|---|---|
| `planner_decomposition` | `trace["planner"]` subset — query_type / pipeline / stage_sequence / selected_top_k / retrieval_budget.reason |
| `retrieval_recalls` | `trace["planner"]["attempts"][*]["verification_reasons"]` (retry 사유) |
| `answer_reasoning` | `trace["synthesis_llm_call"]{user_prompt_text, completion_text}` (Step 4 trace v2 의 신규 키) |

`answer_reasoning` 이 Step 4 의 raw 자료를 *consume*. `BIDMATE_TRACE_FULL=1` 미설정 시 `synthesis_llm_call=None` → `answer_reasoning=None` → aggregate `effective_n["answer_reasoning"]=0` 로 honest 보고. ADR 0054 substantive-only semantics 를 trajectory layer 에 propagate.

### Verifier-axis 의도적 제외

audit sketch 의 원래 3축에 "verifier 판정 정합성" 이 있었으나 Step 4 (trace v2) 작성 중 발견 — `rag_verifier.py` 가 rule-based (LLM call 0건). LLM judge 의 ROI 약함 (sufficiency rule 의 재검증일 뿐). `answer_reasoning` 으로 대체.

*audit findings 도 신규 정보가 들어오면 정정* 가능. audit 자체가 invariant 가 아님.

### 첫 측정 결과

```json
{
  "n": 221,
  "axis_means": {
    "planner_decomposition": 0.479,
    "retrieval_recalls": 0.508,
    "answer_reasoning": null
  },
  "effective_n": {
    "planner_decomposition": 221,
    "retrieval_recalls": 221,
    "answer_reasoning": 0
  },
  "cases_with_synthesis_llm_call": 0
}
```

stub backend 는 SHA-256 uniform [0,1] → 0.5 근처 mean 은 *statistical artifact, signal 아님*. 첫 측정의 의미 = mechanical pipeline 검증 (n=221 cover, bootstrap CI emit, env-off None-skip 정상 작동). 실제 변별력 측정은 LLM backend regen (별 PR scope).

## Cascade pattern

5 step 을 같은 표로 보면:

| step | PR | ADR | 도입 | 발견 |
|---|---|---|---|---|
| 1 | #946 | 0053 | distinguishing-power gauge | 5 metric 중 3개 negative gap (직관에 반함) |
| 2 | #959 | 0054 | scorer semantics fix | metric 정의의 vacuous-truth 함정 |
| 3 | #961 + #963 | — (audit only) | Phase 3+4 audit | rationality rubric 0건, claim_validator 0건 |
| 4 | #965 + #968 | 0055 + — | claim_validator + trace v2 | (audit gap fill) |
| 5 | #987 | 0056 | rationality_judge | (audit gap fill) |

각 step 의 *도입* 이 다음 step 의 *발견* 의 raw 자료가 된다. Step 1 gauge 가 Step 2 함정의 trigger, Step 2+3 audit 결과가 Step 4+5 supply 의 spec, Step 4 trace v2 의 raw 자료가 Step 5 rationality_judge 의 input.

`eval-framework-progressive-audit` 스킬 의 Phase 5 (closed error loop, [#990 audit](../audits/eval-framework-phase5-audit.md)) 가 *본 cascade 가 누적되는지* 자체를 진단했다. Phase 5 audit 의 발견 #1 — `verifier_false_negative_on_unanswerable` 대량 발생 (84% incorrect_answer rate) 가 다음 cascade 의 trigger 후보.

## 일반화 lesson

### (a) 측정 도구의 첫 결과를 신뢰하지 않는다

직관에 반하는 결과는 *시스템 의심* 보다 *metric 의심* 이 우선. (a) metric 정의의 corner case grep 이 falsifiable + 2주, (b) 시스템 갈아엎기는 unfalsifiable + 6개월. 효율 100×.

### (b) 두 번째 측정 surface 가 첫 번째의 sanity check

distinguishing-power gauge (Step 1) 가 *측정의 측정* 역할. 단일 metric 만 봤으면 함정 안 보임. ADR 0001 의 `naive_baseline` 도 같은 패턴 — invariant baseline 이 *다른 측정의 비교축* 역할. 측정 layer 의 hierarchy 가 중요.

### (c) audit 와 implementation 분리

`eval-framework-progressive-audit` 스킬이 *implementation 를 strictly forbid*. audit phase 의 진단이 implementation 의 욕심에 오염되면 진단 객관성 손상. *진단의 결정 깊이* 와 *구현의 결정 깊이* 는 다른 spike. 같은 PR 에 묶으면 둘 다 약해짐.

### (d) escape 의 비대칭성

ALLOW_REGRESSION 은 도입, ALLOW_OVERCLAIM 은 미도입. 비대칭이 옳은 이유 = *escape 의 비용 비대칭*. 통계 정직성은 escape 안 함. 게이트 자체보다 *escape 의 부재* 가 portfolio claim 의 외부 검증 가능성 결정.

### (e) audit 가 발견한 신규 failure mode 는 *다음 cascade 의 trigger*

Phase 5 audit 의 finding #1 (`verifier_false_negative_on_unanswerable` 84%) 가 본 5-step 의 *다음* step 후보. 측정 표면을 닫고 (Step 5) → 닫힌 표면이 새 failure mode 를 노출 → 다음 cascade.

이게 진짜 "closed error loop" 다. 함정 발견 → fix → audit → 자동 게이트 → 측정 표면 → audit → 새 함정. 한 cycle 의 *끝* 이 다음 cycle 의 *시작*.

---

**관련 코드·데이터**

- [ADR 0053 — distinguishing-power gauge](../adr/0053-distinguishing-power-floor-ablations.md)
- [ADR 0054 — conditional-on-answer scorer semantics](../adr/0054-conditional-on-answer-scorer-semantics.md)
- [ADR 0055 — claim_validator as PR gate](../adr/0055-claim-validator-as-pr-gate.md)
- [ADR 0056 — rationality_judge measurement surface](../adr/0056-rationality-judge-measurement-surface.md)
- [Phase 3 audit](../audits/eval-framework-phase3-audit.md) + [Phase 4 audit](../audits/eval-framework-phase4-audit.md) + [Phase 5 audit](../audits/eval-framework-phase5-audit.md)
- [`scripts/distinguishing_power.py`](../../scripts/distinguishing_power.py) — gauge runner
- [`eval/scorers/case.py`](../../eval/scorers/case.py) — scorer (post-ADR 0054)
- [`scripts/validate_claim.py`](../../scripts/validate_claim.py) — PR-body claim 검증 (ADR 0055)
- [`eval/judges/rationality_judge.py`](../../eval/judges/rationality_judge.py) — 3-axis judge (ADR 0056)
- [`reports/real100/rationality.aggregate.json`](../../reports/real100/rationality.aggregate.json) + [`rationality.md`](../../reports/real100/rationality.md) — Step 5 first measurement

**관련 ADR family**

- ADR 0001 — preserve naive baseline (모든 step 의 byte-identical invariant)
- ADR 0003 — answer dict schema_version 2 contract
- ADR 0005 — eval-split public/private (real-eval 의 commit boundary)
- ADR 0006 — LLM-judge on real data only (rationality_judge 도 같은 boundary)
- ADR 0050 — first ALLOW_REGRESSION pattern (corpus 확장 시)
- ADR 0052 — real-eval hardcase expansion n=21 → 221
