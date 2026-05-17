# 0041: Agent budget cap 계약

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0040](./0040-react-agent-loop-additive-preset.md) (ReAct 프리셋),
  [ADR 0003](./0003-structured-answer-citation-contract.md) (답변 계약),
  [ADR 0015](./0015-cost-model-telemetry.md) (cost telemetry),
  issue #673

## TL;DR

- ReAct 루프에 iteration 수 / latency 두 축의 hard cap + token soft telemetry 적용
- cap 초과 시 ADR 0003 `status: insufficient` 보류로 fallback
- env-var 설정 가능, `static` 백엔드 기본값으로 CI 는 항상 LLM-free

## 배경

ADR 0040 에서 도입한 `react_loop` 노드는 근거가 연결되거나 planner 가 `abstain` 을 호출할 때까지 반복한다. 명시적 cap 이 없으면 병적인 쿼리가 무한 LLM 호출을 유발해 latency 폭주, API 비용 폭주, CI 비결정성을 만든다.

세 budget 축이 명시적 계약을 요구한다:
- **Iteration count** — 쿼리당 LLM planning 턴 수
- **Latency** — 루프가 소비할 wall-clock 시간
- **Tokens** — 루프가 강제하지 않지만 비용 귀속용으로 telemetry 노출 (ADR 0015)

## 결정

`react_loop` 노드는 **2축 hard cap** + **1축 soft telemetry** 계약을 강제한다.

### Hard caps (`react_loop` 강제)

| Parameter | Env var | Default | Enforcement |
|---|---|---|---|
| `max_iterations` | `BIDMATE_PLANNER_MAX_ITERATIONS` | 5 | `plan_next` N회 호출 후 루프 종료 |
| `max_latency_ms` | `BIDMATE_PLANNER_MAX_LATENCY_MS` | 8000 | 매 iteration 시작 시 점검, elapsed ≥ cap 이면 종료 |

cap 도달 시:
- 마지막 성공한 `retrieve_evidence` 결과를 `ctx.evidence` 에 설정 (비어있을 수 있음)
- `ctx.evidence` 가 비면 `_phase_build_answer` 가 ADR 0003 보류와 일관되게 `status: insufficient` + `reason: agent_budget_exceeded` 방출
- `stage_attempts` 에 cap-exit 이벤트 기록

### Soft telemetry (비강제)

`input_tokens` / `output_tokens` 는 `stage_attempts` 내 각 `planner_meta` dict 에 기록한다. ADR 0015 cost telemetry 가 쿼리별로 집계한다. 쿼리당 토큰 cap 은 실제 분포 확인 후 도입한다.

### `Planner.plan_next` 에 전달되는 budget dict

```python
budget = {
    "iterations_left": max_iterations - iteration,  # int
    "ms_left": max(0.0, max_latency_ms - elapsed_ms),  # float
}
```

`LLMPlanner` 는 이를 user prompt 에 노출해 LLM 이 자기조절 (`iterations_left == 1` 일 때 `abstain` 선호) 하게 한다.

### 비결정성 허용

`BIDMATE_PLANNER_BACKEND=anthropic` + `temperature=0.0` 일 때:
- Real-eval n=100 점수 분산 ≤ ±2pp 가 `agent_react` 수락 기준 (vs `agentic_full` 기준선)
- ±2pp 초과 시 강제 `temperature=0.0` 점검 + seed-pinning 조사 후 함수 레벨 기본값 승격

## 결과

### 긍정

- Budget cap 으로 latency (p95 ≤ `max_latency_ms` + planning 턴 1회 오버헤드) 와 쿼리당 비용이 bounded
- env-var 설정 가능 — 코드 변경 없이 운영자가 latency / 비용 목표에 맞춰 튜닝
- `BIDMATE_PLANNER_BACKEND=static` (기본) 이면 `max_iterations` 가 LLM 호출 수 아닌 검색 재시도 수가 됨 — CI 는 항상 LLM-free

### 부정 / 트레이드오프

- Hard cap 은 완전 근거 연결 전 루프 종료 가능. 수용: ADR 0003 보류 (`status: insufficient`) 는 에러 아닌 일급 답변
- 운영자마다 기본값 선호 다름 — 테넌트별 config surface 는 follow-up 으로 연기

## Rollback

`eval/config.yaml` 과 `PIPELINE_PRESETS` 에서 `agent_react` 제거. 다른 프리셋은 `react_loop` 에 도달하지 않으며, cap enforcement 코드는 `rag_graph_react._react_loop_node` 에 격리됨.
