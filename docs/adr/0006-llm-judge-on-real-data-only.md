# 0006: LLM-judge 는 real-data 표면 전용

- **Status**: Superseded
- **Superseded by**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers"
- **Date**: 2026-05-11
- **Related**: [ADR 0004](./0004-verifier-retry-policy.md) 정제; [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) 강화
- **Deciders**: hskim

## TL;DR

- LLM-judge 는 `eval/real_config.local.yaml` run 에서만 허용 (synthetic CI 금지).
- deterministic verifier 가 게이트, judge 는 second opinion (`answer.status` 변경 X).
- 핵심 신규 지표: `judge.agreement_with_verifier`.

## 배경

[ADR 0004](./0004-verifier-retry-policy.md) 는 **공개** 경로에서 LLM-as-judge 를 거부했다 — 외부 의존성·쿼리당 토큰 비용·재현성 저하의 세 이유. 그러면서 hedge: *"deterministic 검증기가 천장 닿으면 재고."*

#69 가 천장을 가시화. deterministic 검증기의 `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` knob 가 real-data 에서 4건의 false-abstain 회복 **+** 의도된 보류 2건 뒤집음(`docs/real-data/private-100-doc-experiments.md` Real-data Decision Log 참조). Decision Log 가 trade-off 를 정직하게 기록하지만 **threshold 자체가 임의적** — synthetic eval 튜닝으로는 "real partial answer" 와 "weak hallucination" 을 분리 불가, 둘 다 fraction-of-topics 규칙을 통과한다면. 실제 변별 신호는 *다른 모델의 답변-근거 지지 여부 판독*.

그 신호는 공개 CI 게이트 하기엔 너무 비싸고(토큰) 너무 비재현적. 그러나 **real-data 사이클** 은 이미 수동·aggregate-only·ADR 0005 commit 경계 뒤. second-opinion judge 를 거기 추가는 in-scope; 공개 CI 추가는 out.

## 결정

LLM-as-judge 는 **local real-data eval 표면 전용** 허용:

- **허용**: `eval/real_config.local.yaml` run, judge 출력은 `reports/real100/judge.local.json` (케이스별, git-ignored) + aggregate/agreement 메트릭은 `reports/real100/baseline.aggregate.json` (ADR 0005 allowlist 하 committable)
- **불허**: `eval/config.yaml` (공개 synthetic), `.github/workflows/pr-eval.yml`, `make smoke`, `make eval`. 이 경로는 ADR 0004 따라 deterministic·free·offline·reproducible 유지

### 계약

- judge 는 `(query, answer.summary, evidence[:3].text)` 소비, 구조화 JSON 반환:
  ```json
  {
    "judge_status": "supported" | "partial" | "insufficient",
    "judge_grounded": true | false,
    "judge_reason_short": "string, ≤ 200 chars"
  }
  ```
- deterministic verifier 가 **게이트** 유지. judge 는 **second opinion** — 대체 절대 X. 호출자에게 emit 되는 status 는 항상 verifier 의 것; judge 는 eval aggregate 에만 기여
- judge 파생 aggregate 메트릭:
  - `judge.status_distribution` — `supported`/`partial`/`insufficient` 카운트
  - `judge.grounded_rate` — `judge_grounded == true` 비율
  - **`judge.agreement_with_verifier`** — `judge_status == answer.status` 비율. **핵심 신규 지표.** 하락은 actionable 신호 — verifier 와 judge 불일치, 케이스 보러 가야
- 케이스별 judge 텍스트(`judge_reason_short`·raw prompt·raw 모델 응답)는 **local 유지**. 위 세 aggregate 만 commit 경계 통과

### Cadence

real-data 사이클 나머지처럼 수동. retrieval/verifier 변경 후 `make real-eval-with-judge` 호출, ADR 0005 flow 의 deterministic verifier delta 와 함께 결과 aggregate delta 를 PR 에 첨부.

### 백엔드 pluggability

`scripts/llm_judge.py` 는 `BIDMATE_JUDGE_BACKEND` 통해 backend-agnostic:

- `stub` (default) — deterministic fixture, 네트워크 없음. 테스트용; API key 없이 plumbing 검증
- `openai_compatible` — generic OpenAI-compatible API endpoint(Anthropic-Compatible·OpenAI·vLLM·llama.cpp server 등). `BIDMATE_JUDGE_API_KEY`·`BIDMATE_JUDGE_MODEL` 필요, `BIDMATE_JUDGE_BASE_URL` 선택
- 향후 백엔드는 upstream 파이프라인 손대지 않고 추가 가능

## 결과

**Wins**

- real-data 품질의 독립 신호, `agreement_with_verifier` 통해 deterministic verifier 출력 게이트
- ADR 0005 commit 경계 보존: judge 케이스별 텍스트는 절대 commit 안 됨
- ADR 0004 공개 경로 보존: synthetic CI 는 여전히 deterministic·free·offline·reproducible
- 향후 threshold 튜닝(예: #89)에 synthetic eval set 보다 overfit 어려운 second-opinion 체크 확보

**Costs**

- real-data run 당 토큰 비용 (현재 ~21 케이스 × judge 호출). 수동 cadence + 작은 N 으로 bound
- real-data 표면에 외부 의존성 존재. judge outage 가 deterministic eval 을 깨진 않음 — 그 run 에서 `agreement_with_verifier` 가 단순 미계산
- 사용자가 기억할 것 하나 추가. `make real-eval-with-judge` 가 단계 오케스트레이션으로 완화

**Constraint (ADR 0004 + ADR 0005 불변)**

- 공개 CI 는 외부 LLM 호출 금지. 컨벤션 강제; 공개 표면 스크립트가 `scripts/llm_judge.py` import 안 함
- aggregate-only commit 경계는 `extract_aggregate` + `_assert_no_forbidden` 재귀 가드 재사용으로 강제

## 검토한 대안

- **judge 스킵; deterministic threshold 더 신중 튜닝.** Reject: threshold 가 구조상 임의적. 독립 신호 없으면 tightening 이 false-positive 를 줄인 건지 다른 실패 모드로 옮긴 건지 판별 불가
- **feature flag 뒤로 공개 CI 에 judge 투입.** Reject: ADR 0004 재현성 논거가 공개 경로엔 여전히 유효. synthetic 케이스에 per-PR 토큰 지출도 부당 — 이 케이스들은 모델 없이도 깔끔히 변별 가능
- **LLM-judge 라벨로 deterministic judge 학습.** 시기상조; `agreement_with_verifier` 가 systematic verifier drift 시사하는 임계값 아래로 떨어지면 재고
