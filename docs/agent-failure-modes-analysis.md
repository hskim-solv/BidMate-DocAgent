# Agent 오케스트레이션 실패 모드 분석

> LangGraph 3노드 구조 (`analyze → retrieve_loop → build_answer`) 의 per-node 실패 패턴을 기록한다. 범용 실패 유형은 [docs/failure-cases.md](failure-cases.md) 참조. 이 문서는 **orchestration 수준** — "어떤 노드에서, 어떤 신호로, 어떤 결과가 나오는가"에 집중.

---

## 1. `analyze` 노드 — short-circuit / 무한 재시도 방지

### 1a. Context clarification short-circuit

**패턴**: 후속 질의("그 기관의 납품 일정은?")에서 conversation state 가 비어 있거나 유사도가 임계값 이하일 때, `resolve_conversation_context` 가 `status: needs_clarification` 을 반환.

**그래프 동작**: conditional edge `_route_after_analyze` 가 `"end"` 로 라우팅 → `retrieve_loop` / `build_answer` 미실행. 결과 dict 에 `answer.status = "needs_clarification"`, `answer.claims = []`.

**진단 신호**:
```json
{ "context_resolution": { "status": "needs_clarification", "source": "none", "similarity": 0.0 } }
```

**의도성**: 이 short-circuit 은 오류가 아니라 **설계된 조기 종료**. retrieve_loop 에 잘못된 쿼리를 전달해 false positive 를 만드는 것보다, 사용자에게 context 를 요청하는 게 더 안전.

**위험**: 임계값 (`CONTEXT_RESOLUTION_THRESHOLD = 0.7`) 이 낮으면 real 후속 질문이 full query 로 처리됨. 높으면 short-circuit 이 너무 자주 발생. 현재 합성 eval follow_up accuracy 1.000 (n=21) 이 임계값의 실효성을 검증.

---

### 1b. `MAX_AGENT_ITERATIONS` 초과

**패턴**: `metadata_stage_sequence` 가 반환하는 stage 수가 `MAX_AGENT_ITERATIONS` (현재 코드 내 정의됨) 를 초과하면 `RuntimeError` 를 발생시켜 루프를 차단.

**그래프 동작**: `analyze` 노드에서 예외 — graph run 이 비정상 종료.

**근거**: 무한 retry loop 방지. stage_sequence 는 `metadata_first` + `verifier_retry` 설정에 의해 결정되며, 정상 preset 에서는 이 한도를 초과하지 않음.

**탐지**: 이 예외가 발생하면 새 preset 이 비정상적으로 많은 stage 를 설정했을 가능성 → `eval/config.yaml` 의 신규 preset 추가 시 stage_sequence 길이 확인 필요.

---

## 2. `retrieve_loop` 노드 — retry exhaustion

### 2a. 전체 stage 소진 후 insufficient

**패턴**: strict → reduced → relaxed 3단계를 모두 시도했지만 `verify_evidence` 가 `verified=False` 를 반환. 모든 `stage_attempts[i]["verified"] == False`.

**그래프 동작**: `retrieve_loop` 가 ctx 를 `evidence=[]`, `verified=False` 로 갱신하고 `build_answer` 로 진행. `build_answer` 가 `status: insufficient` 답변 생성.

**진단 신호**:
```json
{
  "retry_count": 2,
  "filter_stage_attempts": [
    {"stage": "strict", "verified": false, "verification_reasons": ["topic_not_grounded"]},
    {"stage": "reduced", "verified": false, "verification_reasons": ["topic_not_grounded"]},
    {"stage": "relaxed", "verified": false, "verification_reasons": ["topic_not_grounded"]}
  ]
}
```

**의도성**: 이 exhaustion 은 **올바른 abstention** 이다 — 인덱스에 해당 정보가 없을 때 허위 답변보다 명시적 기권이 낫다. Real 21-case eval 에서 intended-abstention 4건 중 2건이 이 경로로 올바르게 처리됨.

**위험**: 실제로 relevant evidence 가 있는데도 verifier 가 `topic_not_grounded` 로 판단하면 false abstention. `allow_partial_topic=True` (마지막 시도에서 활성화) 가 이 false abstention 을 줄이는 knob.

---

### 2b. 비교 질의 타깃 누락 후 단방향 답변

**패턴**: `query_type == "comparison"` 에서 balanced top-k 이후에도 한 쪽 타깃 청크가 0개일 때, verifier 가 `missing_comparison_entity` 를 반환해 retry 를 트리거. 마지막 시도에서도 타깃 누락이면 `verified=False` + `evidence=[]` → insufficient.

**진단 신호**:
```json
{ "comparison_coverage": { "after": {"agency_a": 3, "agency_b": 0}, "balanced": false } }
```

**개선 이력**: `apply_comparison_balance` 도입 후 이 패턴 빈도 감소. [docs/comparison-ranking.md](comparison-ranking.md) 참조.

---

## 3. `build_answer` 노드 — synthesis rejection

### 3a. LLM synthesis 가 hallucination 신호 반환

**패턴**: `agentic_full_llm` preset 에서 LLM synthesis 모델이 evidence 밖 내용을 생성. `generate_answer` 가 synthesis_meta 에 경고를 기록.

**그래프 동작**: `build_answer` 가 결과 dict 에 `synthesis: { "fallback_reason": "..." }` 를 포함해 반환. extractive fallback 이 활성화된 경우 extractive claim 으로 대체.

**기본 파이프라인 (`agentic_full`) 에서는 발생 불가**: extractive path 는 LLM synthesis 를 호출하지 않으므로 이 failure mode 는 opt-in (`agentic_full_llm`) 에 한정.

---

### 3b. `_phase_build_answer` 내 cascade — 빈 evidence + non-comparison

**패턴**: `verified=False AND query_type != "comparison"` 일 때 `evidence=[]` 로 갱신됨. `generate_answer` 에 빈 evidence 가 전달되어 `status: insufficient` + `claims: []` 생성.

**진단 신호**:
```json
{ "answer_status": "insufficient", "claim_count": 0, "citation_count": 0 }
```

**의도성**: hallucination 방지를 위한 **정상 abstention**. claim 이 없으면 citation 도 없어 ADR 0003 계약이 자동 준수됨.

---

## 4. 교차 노드 — 타이밍과 cold_start

### 4a. Stage timings 누적 방식

`ctx.stage_timings` 는 모든 phase 에서 `_StageTimer` 로 in-place 업데이트된다. `query_analysis_ms` 는 2번 기록되는데 (iteration 1 + iteration 2), `_StageTimer` 는 이 경우 **누적** 으로 합산한다.

`stage_latency` 결과 키에는 최종 합산값이 들어간다. per-attempt `retrieve_ms` / `verify_ms` 는 `filter_stage_attempts[i].timings` 에 별도 보관.

### 4b. Cold-start 결과에 미치는 영향

첫 번째 `run_rag_query` 호출에서 `cold_start=True` 가 설정되고 모듈 레벨 캐시 (BM25 인덱스 등) 가 초기화된다. 성능 프로파일 테스트는 `monkeypatch.setattr(rag_core, "_PROCESS_WARM", False)` 로 각 호출을 cold-start 동일 조건으로 만든다.

---

## 요약 매트릭스

| 노드 | 실패 모드 | 그래프 동작 | 진단 신호 | 의도적? |
|---|---|---|---|---|
| `analyze` | context clarification 필요 | `END` 로 short-circuit | `context_resolution.status=needs_clarification` | ✅ |
| `analyze` | MAX_AGENT_ITERATIONS 초과 | RuntimeError | — | ✅ (안전장치) |
| `retrieve_loop` | stage 전체 소진 | insufficient 로 진행 | `retry_count=2, all verified=false` | ✅ (abstention) |
| `retrieve_loop` | 비교 타깃 누락 | retry → exhaustion | `comparison_coverage.after[X]=0` | ⚠️ (개선 여지) |
| `build_answer` | LLM synthesis 실패 | extractive fallback | `synthesis.fallback_reason` | ✅ (opt-in 전용) |
| `build_answer` | 빈 evidence cascade | insufficient | `claim_count=0, citation_count=0` | ✅ (abstention) |

> 성능 측정과 overhead quantification: [tests/test_langgraph_performance_profile.py](../tests/test_langgraph_performance_profile.py). 시스템 설계 STAR: [docs/agent-system-design-case-study.md](agent-system-design-case-study.md).
