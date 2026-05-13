# Model upgrade playbook — LLM 모델 교체를 안전하게

BidMate-DocAgent는 두 곳에서 LLM을 호출합니다. 한 쪽 모델만 바뀌어도
나머지 surface의 측정·운영은 영향을 받지 않게 분리되어 있습니다.

| Surface | 코드 경로 | 영향 | 모델 env |
|---|---|---|---|
| **Synthesis (production)** | [`rag_synthesis.py`](../rag_synthesis.py), `agentic_full_llm` preset | 사용자 응답의 `summary` / `answer_text` 재작성 (ADR 0011) | `BIDMATE_SYNTHESIS_MODEL` |
| **Judge (eval only)** | [`eval/llm_judge.py`](../eval/llm_judge.py) | 평가 점수 (ADR 0006/0012) | `BIDMATE_JUDGE_MODEL` |

추출(extractive) 경로 — `naive_baseline`, `agentic_full` — 는 LLM을 호출하지
않으므로 모델 업그레이드 영향이 0입니다 (ADR 0001 / 0003 invariant). 이 분리가
playbook 절차를 짧게 만드는 핵심입니다.

본 문서는 stub/anthropic/openai 3-backend 자체의 도입 결정
([ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md))은 다루지 않고,
**해당 backend 내부에서 모델 버전이 바뀔 때의 운영 절차**만 다룹니다. 백엔드
선택 자체는 ADR 0011, 평가 측 백엔드 선택은 ADR 0006/0012를 참고하세요.

---

## When to trigger

업그레이드를 실제로 돌릴 만한 4가지 트리거. 우선순위는 위→아래.

1. **Provider deprecation** — 사용 중 모델이 sunset 일정 공지됨. 비선택. 데드라인
   역산해서 step 1-3을 끝낼 시간을 확보.
2. **Capability 상향 릴리스** — provider가 같은 가격대에 더 강한 모델을 냄
   (예: Sonnet 4.6 → 4.7). step 3(cost delta)이 ≤ 0이면 거의 무조건 채택.
3. **단가 인하** — 같은 capability tier에서 $/Mtok가 하락. step 1-2를 통과하면
   cost-only upgrade. 가장 안전한 케이스.
4. **회귀 제보** — production에서 grounding/citation 회귀 보고. step 1을
   먼저 돌려 원인이 모델인지 prompt인지 분리. 모델이 원인이면 **roll back**이
   먼저, upgrade는 그 다음.

비 트리거: "최신이라서". 1-3 정량 근거가 없으면 step 0에서 멈춥니다.

---

## Decision criteria (gate)

다음 정량 기준을 **모두** 통과해야 rollout 합니다. n=42 + 95% CI bootstrap
(seed=17, 1000 resamples) 기준 — [`reports/eval_summary.json`](../reports/eval_summary.json)
포맷.

| Metric | 통과 기준 | 출처 (eval_summary.json) |
|---|---|---|
| `citation_precision` | regression ≤ 2pp **또는** CI overlap | 후보 run의 `ablation.runs[name=full_llm].citation_precision` |
| `claim_citation_alignment` | regression ≤ 1pp | 같은 row의 `claim_citation_alignment` |
| `groundedness` (전체) | regression ≤ 5pp | 같은 row의 `groundedness` |
| `abstention.accuracy` | 변동 ≤ 5pp (양방향) | 같은 row의 `abstention` 블록 |
| `stage_latency.answer_generation_ms.p95` | 회귀 ≤ 30% | 같은 row 또는 top-level `stage_latency` (extractive+synthesis 합산) |
| Synthesis-only cost / query | 변동 ≤ ±25% | step 3 — provider 가격 × 외부 trace 백엔드 토큰 카운트 (eval_summary에 없음) |
| `schema_version` | bump 없음 (`2` 유지) | `outputs/answer.json.answer.schema_version` |
| Synthesis fallback rate | 절대 0 유지 | `reports/traces/<run>/<case>.trace.json` 의 synthesis span (없으면 fall-back 가능) |

핵심 invariant — **하나라도 실패하면 rollout 중단**:
- `schema_version: 2` 그대로 (ADR 0003).
- `used_chunk_ids ⊆ evidence.chunk_ids` 가드 ([`rag_synthesis.py:79`](../rag_synthesis.py)) 가
  새 모델에서도 fall-back 0으로 통과. fall-back이 1건이라도 발생하면 prompt
  regression으로 분류 (step 2).
- `naive_baseline` / `agentic_full` 점수는 모델 무관 — **두 row가 흔들리면
  업그레이드 외 변경이 섞인 것**. 분리부터.

---

## 5-step procedure

각 단계의 명령은 worktree 루트에서 실행한다고 가정합니다.

### Step 0 — baseline 고정

upgrade 직전 baseline을 한 번 더 재현해서 비교 reference를 명시적으로 박습니다.
대부분 `make real-eval` 산출물로 충분하지만, **현재 commit의** `reports/eval_summary.json`
이 baseline임을 명확히 하기 위해 한 번 더 돌리는 게 안전합니다.

```bash
# Synthesis surface — production 모델 기준
mkdir -p reports/upgrade/baseline

BIDMATE_SYNTHESIS_BACKEND=anthropic \
BIDMATE_SYNTHESIS_MODEL=claude-sonnet-4-6 \
  python3 eval/run_eval.py \
    --config eval/config.yaml \
    --output_dir reports/upgrade/baseline

# Judge surface — 측정 도구 자체의 모델 (별도 upgrade일 때만)
# BIDMATE_JUDGE_BACKEND=anthropic BIDMATE_JUDGE_MODEL=<current> \
#   python3 eval/llm_judge.py --input reports/upgrade/baseline/traces ...
```

생성 위치: `reports/upgrade/baseline/eval_summary.json` + `reports/upgrade/baseline/traces/`.
경로 전체가 `reports/*` git-ignore 안쪽이라 raw 응답을 그대로 두어도 됩니다 (ADR 0005
boundary). commit이 필요하면 [Step 3](#step-3--cost-delta) 의 aggregate 표만 추출.
Bootstrap CI seed는 [`eval/bootstrap.py:DEFAULT_SEED`](../eval/bootstrap.py) (현재 17)
에 고정되어 있어 CLI 플래그 없이 동일한 reshuffle 패턴이 재현됩니다.

### Step 1 — Shadow eval (새 모델로 같은 케이스 재실행)

같은 seed/preset/케이스로 새 모델을 한 번 돌립니다. **다른 변수는 동결**.

```bash
mkdir -p reports/upgrade/candidate

BIDMATE_SYNTHESIS_BACKEND=anthropic \
BIDMATE_SYNTHESIS_MODEL=claude-opus-4-7 \
  python3 eval/run_eval.py \
    --config eval/config.yaml \
    --output_dir reports/upgrade/candidate
```

산출물 비교는 **두 단계**로 합니다.

**(a) Primary run sanity check** — `compare_eval.py` 는 `eval/config.yaml` 의
`primary_run` (현재 `naive_baseline`, extractive) 만 비교합니다. 모델 변경은
이 row 에 영향이 없어야 하므로 **모든 metric이 동일** 해야 정상:

```bash
python3 scripts/compare_eval.py \
  --base reports/upgrade/baseline/eval_summary.json \
  --head reports/upgrade/candidate/eval_summary.json \
  --title "sonnet-4-6 → opus-4-7 — primary sanity" \
  > reports/upgrade/primary_sanity.md
```

여기서 Δ가 0 이 아니면 모델 외 변경이 섞인 것 — 즉시 디버그.

**(b) `full_llm` row 직접 비교** — `compare_eval.py` 가 ablation 행을 지원하지
않으므로 `jq` 로 추출해서 수동 diff. 본 playbook 가 자동화하기 전 한정한
fallback:

```bash
for FIELD in accuracy groundedness citation_precision claim_citation_alignment \
             abstention answer_format_compliance; do
  echo "--- $FIELD ---"
  jq -r --arg f "$FIELD" \
    '.ablation.runs[] | select(.name=="full_llm") | "\(.name)\t\(.[$f])"' \
    reports/upgrade/baseline/eval_summary.json \
    reports/upgrade/candidate/eval_summary.json
done > reports/upgrade/full_llm_delta.txt
```

산출된 `full_llm_delta.txt` 의 각 metric 을 [Decision criteria](#decision-criteria-gate)
의 임계값과 대조. CI overlap이면 통계적 동등으로 처리 (README "Ablation 해석"
절). 이 수동 단계는 model_shift_check 하네스가 생기면 한 명령으로 흡수될 후보 —
[Limitations](#limitations-의도된-한계) 참조.

### Step 2 — Prompt regression (계약·가드 회귀 검사)

산출물 자체가 ADR 0003 계약을 깨지 않았는지 확인. metric은 통과해도 응답
shape가 바뀌면 downstream tooling이 깨집니다.

체크리스트:

1. **schema_version invariant**: `jq '.answer.schema_version' outputs/answer.json` 가
   여전히 `2`. bump 시 별도 ADR (ADR 0003 explicit).
2. **Fall-back 카운트**: synthesis가 가드 ([`rag_synthesis.py:97-105`](../rag_synthesis.py)
   의 `(None, meta_with_fallback_reason)` 패턴) 에 걸려 extractive로 떨어진 케이스가
   1건이라도 있으면 prompt mismatch 가능성 — 시스템 프롬프트
   ([`rag_synthesis.py:53-64`](../rag_synthesis.py)) 와 새 모델의 instruction
   following 패턴 불일치 의심. 검사 경로: `reports/upgrade/candidate/traces/<case>.trace.json`
   의 synthesis span (혹은 trace 백엔드 enable 시 LangFuse UI 의 `synthesis` span
   metadata).
3. **인용 grounding 회귀 카운트** ([`docs/real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md))
   : `jq '.citation_grounding_error_counts' reports/upgrade/{baseline,candidate}/eval_summary.json`
   의 6 카테고리 카운트가 어느 하나도 증가하지 않음. 증가하면 모델이 새 grounding
   패턴을 만들고 있다는 신호 — verifier 가 잡지 못하는 미세 회귀.
4. **Korean RFP 한정 도메인 회귀**: 비교 슬라이스에서 `target` 이 `"기관 A"` /
   `"기관 B"` 표기 일관성을 유지하는지. 일부 모델은 `"기관A"` / `"agency_a"`
   처럼 normalization을 시도하므로 verifier 가 weakens.
5. **Trace 시각 검증** (선택): [`docs/observability.md`](observability.md) 에
   따라 LangFuse / OTLP 로 candidate run 한 케이스만 흘려 trace UI 에서 응답을
   사람 눈으로 확인. 회귀가 의심될 때만.

### Step 3 — Cost delta

provider 가격 카드 × `stage_latency.synthesis` × 평균 token 사용량.

**Latency (eval_summary에서 추출):**

```bash
# stage_latency.answer_generation_ms 는 extractive + synthesis 합산.
# synthesis 단독 latency 는 trace 백엔드 (LangFuse / OTLP) 의 synthesis span
# 에서 직접 읽어야 합니다 — docs/observability.md 참고.
jq '.stage_latency.answer_generation_ms' \
  reports/upgrade/baseline/eval_summary.json \
  reports/upgrade/candidate/eval_summary.json
```

**Token 사용량과 비용 (eval_summary에는 없음 — 외부 instrumentation 필요):**

현재 `eval_summary.json`은 토큰 카운트를 집계하지 않습니다. 두 경로 중 하나로
보강:

1. **Trace backend** — `BIDMATE_TRACE_BACKEND=langfuse` (또는 otel) 로 candidate run을
   재실행. LangFuse UI / OTLP collector 에서 synthesis span의 `usage.input_tokens` /
   `output_tokens` 를 집계 ([`docs/observability.md`](observability.md) 참고).
2. **Provider 콘솔** — Anthropic console 의 usage 페이지에서 run 시간대 토큰을
   읽고 query 수 (`config.cases` 길이 × ablation runs 중 LLM-호출 row 수) 로 나눔.
   거친 추정이지만 첫 사이클에는 충분.

표 형식 (실측 값으로 교체):

| Item | Baseline (sonnet-4-6) | Candidate (opus-4-7) | Δ |
|---|---:|---:|---:|
| Input $/Mtok (price card date: YYYY-MM-DD) | TBD | TBD | TBD |
| Output $/Mtok | TBD | TBD | TBD |
| Mean input tokens / query (cached) | TBD | TBD | TBD |
| Mean output tokens / query | TBD | TBD | TBD |
| **Mean cost / query** | TBD | TBD | TBD |
| `stage_latency.answer_generation_ms.p95` (전체) | TBD | TBD | TBD |

> 가격 카드는 시점 변동성이 큽니다 — 표 옆에 `Date: YYYY-MM-DD` 명시 필수.
> Anthropic 공식 가격 페이지를 source of truth로 사용.

이 표가 [Decision criteria](#decision-criteria-gate) 의 마지막 두 줄
(latency / cost) 을 평가하는 근거입니다.

### Step 4 — Rollout

현재 시스템은 트래픽이 없는 상태이므로 (Phase 3 데모 배포 후 진짜 canary 가
가능) 단계는 환경 변수 전파 순서로만 표현합니다.

| 단계 | 환경 | 검증 |
|---|---|---|
| 1 | 로컬 / `make smoke` | smoke pass + 응답 spot-check |
| 2 | CI eval (별도 branch, eval-only) | `pr-eval.yml` delta 코멘트가 [Decision criteria](#decision-criteria-gate) 통과 |
| 3 | Real-eval (private 100-doc) | `make real-eval-delta` 가 통과, aggregate 차이만 commit (ADR 0005) |
| 4 | 데모 배포 (`BIDMATE_SYNTHESIS_BACKEND=anthropic` 가 활성화된 환경) | 첫 24시간 trace를 LangFuse 에서 sample 5건 사람 검토 |

진짜 canary % 분할은 **트래픽이 생기는 Phase 3 이후** 단계로 미룸. 그 시점에
다시 본 문서를 펴서 단계 5 라인 (예: 5% → 25% → 100% over 1 week, 각 단계마다
abstention rate / citation precision 알람) 을 추가 예정.

### Step 5 — Rollback

ADR 0011 의 stub fallback 패턴을 그대로 활용. 진단 신호 → 동작 매핑:

| 트리거 | 동작 |
|---|---|
| `synthesis_fallback_rate` 가 0이 아님 | `BIDMATE_SYNTHESIS_BACKEND=stub` (즉시 deterministic) |
| `citation_precision` 이 baseline 대비 > 5pp 회귀 (24h rolling) | 같은 backend 유지, `BIDMATE_SYNTHESIS_MODEL` unset → `DEFAULT_ANTHROPIC_MODEL` (현재 `claude-sonnet-4-6`) 로 복귀 |
| Provider 5xx 가 1분당 > 3건 | `BIDMATE_SYNTHESIS_BACKEND=stub` + provider 상태 확인 |
| 비용이 예측치 대비 2× | rate limit (배포 환경 측) + step 3 재계산 |

rollback 은 **non-destructive**: stub 으로 떨어져도 응답은 deterministic
extractive 로 계속 나갑니다 (ADR 0011 / 0003 invariant). 시간 압박 안 받고
원인 분석 가능.

---

## Worked example — sonnet-4-6 → opus-4-7

> **Status: 미실측.** 본 문서가 머지될 시점에 `ANTHROPIC_API_KEY` 가 setup 되지
> 않은 상태였습니다. Phase 3 데모 배포 단계에서 키를 준비할 때 아래 시퀀스를
> 한 번 돌려 실측 표를 채울 예정입니다. 명령은 위 5-step 의 정확한 플래그를
> 그대로 재사용합니다 (드라이런으로 한 번 검증된 명령).

명령 시퀀스 (그대로 복붙해서 실행 가능):

```bash
mkdir -p reports/upgrade/baseline reports/upgrade/candidate

# 1. Baseline run (현재 default 모델)
BIDMATE_SYNTHESIS_BACKEND=anthropic BIDMATE_SYNTHESIS_MODEL=claude-sonnet-4-6 \
  python3 eval/run_eval.py --config eval/config.yaml \
    --output_dir reports/upgrade/baseline

# 2. Candidate run (업그레이드 후보)
BIDMATE_SYNTHESIS_BACKEND=anthropic BIDMATE_SYNTHESIS_MODEL=claude-opus-4-7 \
  python3 eval/run_eval.py --config eval/config.yaml \
    --output_dir reports/upgrade/candidate

# 3. Delta
python3 scripts/compare_eval.py \
  --base reports/upgrade/baseline/eval_summary.json \
  --head reports/upgrade/candidate/eval_summary.json \
  --title "sonnet-4-6 → opus-4-7" \
  > reports/upgrade/delta.md
```

예상 결과 패턴 (n=42 + bootstrap 의 검출 한계 기준 — 실측 후 검증):

- **Synthesis 의 추출-가드가 강해서 quality metric은 거의 동등하게 나올 가능성**:
  citation_precision / claim_citation_alignment / abstention 의 candidate 변동은
  CI 폭 안에 잡힐 가능성이 큼 (README "Ablation 해석" 절의 CI 분리 기준과 동일).
  즉 "통계적으로 다르지 않음" → quality gate 통과.
- **Latency / cost 는 ↑** (opus 가 sonnet 보다 무거움 + 비쌈).
- **결정**: capability 상향이 cost gate (≤ ±25%) 를 못 통과하면 채택하지 않음.
  남는 활용처는 production synthesis 가 아니라 별도 high-stakes hard-case 경로
  — 별도 ADR 후보.

가설 메타-결론: **synthesis는 추출 가드 덕에 모델 차이를 흡수합니다. LLM
자유도가 적기 때문에 ROI가 가장 큰 model upgrade는 응답 surface가 아니라
judge surface ([`eval/llm_judge.py`](../eval/llm_judge.py))** — 측정 신호의
noise floor 자체를 낮춤. 실측 후 본 결론이 바뀌면 윗 줄을 수정.

---

## Judge surface 업그레이드

LLM judge 는 평가 도구. production 응답 품질은 영향 없지만 **eval 신호의
정확도**가 바뀝니다 (ADR 0006 / 0012). 절차는 위 5단계와 동일하되:

- `BIDMATE_SYNTHESIS_MODEL` → `BIDMATE_JUDGE_MODEL` 로 치환.
- Decision criteria 의 `verifier_agreement` (judge 의 자체 일관성 metric)
  가 핵심. 다른 quality metric 은 평가 도구가 바뀐 거지 시스템이 바뀐 게
  아니므로 비교 기준이 다름.
- Token budget guard: `BIDMATE_JUDGE_TOKEN_BUDGET` (기본 200K input). 새 모델이
  비싸면 이 한도부터 재설정 — [`eval/llm_judge.py:301`](../eval/llm_judge.py) 의 경고
  메시지가 트리거.
- Rollback: `BIDMATE_JUDGE_BACKEND=stub` 이 zero-cost deterministic fallback
  (`eval/llm_judge.py:18`).

production / eval 두 surface 를 **동시에 upgrade 하지 않습니다.** 그러면
quality 회귀가 모델 때문인지 평가 도구 때문인지 분리 불가.

---

## Limitations (의도된 한계)

- **트래픽이 아직 없습니다.** 단계 4 의 진짜 canary % 분할은 Phase 3 데모
  배포 이후로 미뤄짐. 그때까지는 "환경 변수 전파 순서" 가 rollout 의 대용물.
- **Cost 표는 점 추정.** provider 가격 카드 시점 변동 + 평균 토큰 사용량이
  쿼리 분포에 따라 흔들림. real-eval (n=100) 의 aggregate 만 commit (ADR 0005).
- **자동화된 model_shift_check 하네스는 아직 없음.** 본 문서의 step 1 `full_llm`
  row 추출이 `jq` 한 줄 — [`scripts/compare_eval.py`](../scripts/compare_eval.py)
  가 primary run 만 비교하기 때문. 이를 묶는 `scripts/model_shift_check.py`
  single-command 가 생길 가치가 있지만, 두세 번 실제 업그레이드를 해본 뒤
  패턴이 굳을 때 ADR 0015 후보로 분리. premature abstraction 회피.
- **Token 사용량 / 비용은 eval 산출물에 없음.** step 3 는 trace 백엔드
  (LangFuse / OTLP) 또는 provider 콘솔 usage 페이지에서 직접 수집. 자동 추출
  pipeline 은 향후 enhancement.
- **공개 synthetic 의 검출 한계.** n=42 + bootstrap 95% CI 는 작은 quality
  변화를 통계적으로 분리하지 못함 (README "Ablation 해석" 절). 실제 분리는
  real-eval (n=100) + private 가 있어야 — 본 playbook 의 단계 3 / step 4 의
  3번 줄.

---

## Cross-references

- [ADR 0003](adr/0003-structured-answer-citation-contract.md) — `schema_version: 2` 계약, model upgrade 시 invariant.
- [ADR 0006](adr/0006-llm-judge-on-real-data-only.md) — Judge backend pattern (stub default).
- [ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md) — Synthesis backend toggle. **본 playbook 의 전제**.
- [ADR 0012](adr/0012-llm-judge-on-public-synthetic.md) — Public synthetic 에서의 judge stub 정책.
- [`docs/answer-policy.md`](answer-policy.md) — schema_version 호환성 가드 코드 위치.
- [`docs/observability.md`](observability.md) — LangFuse / OTLP trace 백엔드, step 2 의 trace 검증에 사용.
- [`docs/deployment.md`](deployment.md) — 데모 배포 시점에 본 playbook 의 단계 4 가 production 으로 승격.
- [`docs/real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) — Step 2 의 6 카테고리 회귀 카운트 정의.
