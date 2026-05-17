# 0040: ReAct agent loop을 추가 파이프라인 프리셋으로

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline 불변식),
  [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (additive opt-in 패턴),
  [ADR 0020](./0020-protocol-based-pluggability.md) (4-axis 플러그가능성),
  [ADR 0022](./0022-langgraph-orchestration-stage-1.md) (LangGraph 통합),
  [ADR 0023](./0023-hyde-query-expansion-ablation.md) (쿼리 확장 패턴),
  [ADR 0024](./0024-agentic-full-llm-as-api-default.md) (3-layer 기본값 정책),
  [ADR 0041](./0041-agent-budget-cap-contract.md) (budget cap),
  issue #673

## TL;DR

- 프로젝트명 "DocAgent"가 함의하는 자율 에이전트성을 채우기 위해 `agent_react`를 네 번째 `PIPELINE_PRESETS`로 추가 (additive opt-in).
- `Planner` Protocol을 5번째 pluggable 축으로 도입; `StaticPlanner`(deterministic, CI 기본값) + `LLMPlanner` (`BIDMATE_PLANNER_BACKEND=anthropic` 활성화).
- ADR 0001 / 0003 / 0024 모두 보존; `agent_react`는 explicit opt-in only, 기본값 변경 없음.

## 배경

Phase 1 audit (2026-05-14)가 BidMate-DocAgent가 stage (B) "agentic RAG"임을 발견 — LangGraph orchestration과 bounded 검증기 retry 존재하지만 `make_plan`은 결정론적 정적 함수이며 query-time LLM-driven action 선택(ReAct 패턴) 부재.

프로젝트명 "DocAgent"가 자율 근거 검색 에이전트성을 함의. 이름과 구현 간격을 좁히고 시니어 엔지니어링 portfolio signal(trade-off 문서화 + 확장 가능 아키텍처 + eval 규율) 생산을 위해 ReAct agent loop을 **additive** 네 번째 파이프라인 프리셋으로 도입.

외부 리뷰어 critique (ADR 0024 배경) 및 senior-positioning rubric (docs/senior-positioning.md) 모두 "언제 진짜 에이전트로 업그레이드?"를 핵심 signal 질문으로 플래그 — 이 ADR이 문서화된 답.

## 결정

`agent_react`를 네 번째 `PIPELINE_PRESETS` 항목 (`rag_pipeline_presets.py`), alias `"react"`로 추가. `rag_graph_agentic_full.py`와 병행 `rag_graph_react.py` LangGraph 모듈 도입.

**이전 ADR 세 불변식 무변 보존:**

1. **ADR 0001**: `naive_baseline` 골든 bit-identical. `_skip_graph=True` + direct-path guard (`pipeline != "naive_baseline"`) 유지; `agent_react`는 `BIDMATE_ORCHESTRATOR` 검사 *이전* 새 branch 추가, *내부* 아님.

2. **ADR 0003**: answer dict 계약 (`schema_version: 2`) 무변. `_phase_build_answer` 재사용; `react_loop`는 `ctx.evidence` + `ctx.plan`만 populate — 답변 생산 안 함.

3. **ADR 0024 3-layer 기본값 정책**:
   - CLI 기본값 `naive_baseline` 유지.
   - 함수 기본값 `agentic_full` 유지.
   - API surface 기본값 `agentic_full_llm` 유지.
   `agent_react`는 explicit `pipeline="agent_react"` 또는 alias `"react"`로만 opt-in.

**`Planner` Protocol (ADR 0020 확장):**
`rag_planner.Planner`가 다섯 번째 Protocol 기반 pluggable 축, `VectorStore`, `QueryExpander`, `Reranker`, 미래 `Synthesizer`와 합류. `StaticPlanner`가 `make_plan` 위임 (결정론적 기본값). `LLMPlanner`가 `BIDMATE_PLANNER_BACKEND=anthropic`으로 활성화.

**CI 계약:**
`BIDMATE_PLANNER_BACKEND=static` (기본값)이 모든 `agent_react` 테스트를 결정론적 유지 — CI에서 Anthropic API 호출 없음.

## 결과

### Positive

- "DocAgent" 이름이 이제 진정한 ReAct agent loop으로 backing.
- ADR 0020 4-axis 플러그가능성이 5-axis로 확장 (Planner).
- `agent_react` 프리셋이 `agentic_full`과 side-by-side 비교 가능한 독립 eval 행 생산.
- `BIDMATE_PLANNER_BACKEND` env-var 패턴이 ADR 0011 + ADR 0023 opt-in 컨벤션과 일관.

### Negative / Trade-offs

- **`BIDMATE_PLANNER_BACKEND=anthropic` 시 non-determinism**: LLM 샘플링이 variance 도입. `temperature=0.0` + ADR 0041 budget cap으로 완화; 실 eval n=100 ±2pp 허용오차가 수락 기준.
- **Latency 증가**: 다턴 LLM 계획이 p95 latency 추가. ADR 0041이 `max_iterations=5` / `max_latency_ms=8000` cap 강제.
- **Cost**: 각 계획 턴이 billable API 호출. tool 정의의 `cache_control: ephemeral` + ADR 0015 cost telemetry로 완화.
- **공격 표면**: tool_use 결과가 주입 명령 운반 가능. ADR 0042 evidence-boundary 방어로 완화 (PR-E).

## 검토한 대안

1. **`_phase_retrieve_loop`을 ReAct loop으로 재작성**: 기각. Load-bearing 경로 수정(ADR 0001 위험) + `tests/test_langgraph_orchestrator_regression.py`의 JSON-identity 회귀 깸.

2. **별도 agent 프레임워크 (CrewAI, AutoGen) 사용**: 기각. 신규 paid/maintained 의존성 추가, LangGraph 투자(ADR 0022) 깸, 단일 파이프라인 프리셋에 비례 안 맞음.

3. **Full multi-agent 시스템 (planner + retriever + verifier agents)**: deferral. 다문서 스트리밍, inter-agent 상태 동기화, 신규 eval surface 필요 — `agent_react`가 단일 agent loop 검증한 후 follow-up milestone로 더 잘 scoped.

## Upgrade 경로

`agent_react`가 "언제 업그레이드?" 답. `agentic_full`로부터 upgrade 조건:
- 외부 리뷰어가 실 eval에서 p95 latency ≤ budget cap 확인.
- Cost telemetry가 per-query cost가 operator budget 내임을 표시.
- `agent_react`가 LLM-judge recall@20 메트릭에서 공개 합성 슬라이스(ADR 0012 eval surface)에서 `agentic_full` 대비 ≥ 2pp.

세 조건 모두 충족까지 `agentic_full`이 함수 레벨 기본값 유지 (ADR 0024).
