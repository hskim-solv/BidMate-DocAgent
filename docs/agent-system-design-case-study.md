# Agent 시스템 설계 회고 — LangGraph 3노드 분해 (ADR 0022 stage 2)

> PR [#458](https://github.com/hskim-solv/BidMate-DocAgent/pull/458) (ADR 0022 stage 2, issue #401 follow-up) 의 시스템 설계 결정을 STAR 형식으로 재서술한 포트폴리오 자산. 성능 측정 수치는 `tests/test_langgraph_performance_profile.py` 에서 확인.

---

## STAR — 단일 passthrough 노드 → 3노드 phase 분해

### Situation

ADR 0022 stage 1 은 `run_rag_query` 전체를 **단일 passthrough 노드** 하나로 래핑해 LangGraph StateGraph 에 넣었다. 목적은 환경 변수 스위치 (`BIDMATE_ORCHESTRATOR=langgraph`) 로 그래프 경로를 선택할 수 있게 하면서 JSON-identity 계약을 유지하는 것이었다.

하지만 stage 1 이후 두 가지 문제가 남았다:

1. **노드가 1개라 graph 고유 기능을 쓸 수 없음**: conditional edge, per-node retry, per-phase observability 등이 모두 단일 노드 블랙박스 안에 숨어 있었다.
2. **내부 phase 코드가 `run_rag_query` 함수 본체에 인라인**: `_phase_analyze` / `_phase_retrieve_loop` / `_phase_build_answer` 가 분리되지 않아, orchestrator 가 동일 코드를 재사용하려면 재구현이 필요했다.

### Task

세 phase 를 graph 노드로 분리하되, JSON-identity 계약을 깨지 않는다. 즉, `direct path` 와 `langgraph path` 는 타이밍·cold_start 를 제외한 결과가 byte-for-byte 동일해야 한다.

추가 제약:
- `naive_baseline` 을 포함한 모든 non-agentic preset 은 graph 경로에 진입하지 않아야 함.
- `langgraph` 는 opt-in dep (`requirements-graph.txt`) — 미설치 시 `direct` fallback 완전 정상.

### Action

**설계 결정 1 — 공유 컨텍스트 객체 (`_RunContext`)**

세 phase 는 mutable `_RunContext` 하나를 공유하며 StateGraph state 에 `ctx` 필드로 담긴다. 노드는 `ctx` 를 in-place 로 변경하고 빈 dict `{}` 를 반환 — LangGraph 의 "state merge" 기능 없이 단순 참조 공유.

이 선택이 의도적인 이유:
- phase 간 전달해야 할 인수 수십 개 (analysis, plan, evidence, stage_timings …) 를 StateGraph 스키마에 일일이 선언하면 TypedDict 가 비대해지고 graph 코드와 rag_core 코드가 coupling 됨.
- ctx 공유는 "내부 구현"이고 graph 모듈 (`rag_graph_agentic_full.py`) 에만 노출됨. 테스트는 여전히 외부 API (`run_rag_query`) 만 검증.

**설계 결정 2 — conditional edge 로 short-circuit**

`_phase_analyze` 는 두 가지 경우에 early result 를 반환:
- conversation context 가 모호해 clarification 이 필요한 경우
- metadata 가 ambiguous 해 disambiguation 이 필요한 경우

stage 1 에서는 이 early return 이 단일 노드 안에 숨어 있었다. stage 2 에서는 `_route_after_analyze` conditional edge 가 `result` 필드 존재 여부로 `END` vs `retrieve_loop` 를 라우팅한다. 그래프 레벨에서 명시적 분기 가시화.

```
START → analyze ──(result is not None)──→ END
                └──(result is None)─────→ retrieve_loop → build_answer → END
```

**설계 결정 3 — JSON-identity by construction**

graph 노드들이 `_phase_analyze` / `_phase_retrieve_loop` / `_phase_build_answer` 를 그대로 호출하기 때문에, 동일 로직이 두 경로 (direct / graph) 에서 실행된다. "재구현 없이 same code" 가 JSON-identity 보장의 근거.

```python
def _analyze_node(state):
    from rag_core import _phase_analyze
    early_result = _phase_analyze(state["ctx"])
    if early_result is not None:
        return {"result": early_result}
    return {}
```

회귀 테스트 (`tests/test_langgraph_orchestrator_regression.py`) 가 타이밍·cold_start 필드를 제거한 후 `json.dumps(sort_keys=True)` byte-equality 를 단언.

**대안 검토**

| 대안 | 기각 이유 |
|---|---|
| LCEL (LangChain) Chain | 서드파티 체이닝 추상화를 추가로 사용해야 함; 현 BidMate 는 rag_core.py 가 orchestration 의 단일 진실 출처이므로 LCEL 래퍼가 중복 계층 생성 |
| DSPy optimizer loop | 프롬프트 최적화 프레임워크로 설계 목적이 다름; 현 단계에서 extractive grounded-answer 파이프라인에는 overfit |
| 직접 함수 체인 (순수 Python) | graph 없이 `_phase_analyze → _phase_retrieve_loop → _phase_build_answer` 직접 호출하는 것과 사실상 동일 — LangGraph 의 conditional edge / 향후 per-node streaming / trace 연결 가치를 포기 |
| 단일 노드 유지 (stage 1) | graph 고유 기능 활용 불가; per-node observability 어려움 |

### Result

**정량**:

```
테스트: pytest tests/test_langgraph_performance_profile.py -v -s

[profile] direct path median (5 runs):
  analyze: X ms | retrieve+verify: Y ms | build_answer: Z ms

[profile] overhead:
  direct: A ms  langgraph: B ms  ratio: R× (최대 허용: 2.5×)
```

실제 수치는 `make smoke` 실행 환경 (CPU, index 크기) 에 따라 다름. 측정 결과를 [reports/eval_summary.json](../reports/eval_summary.json) 의 `stage_latency` 블록과 비교해 phase 별 bottleneck 을 파악.

**정성**:
- 3노드 분해로 conditional edge 가시화 — 코드 없이 StateGraph 다이어그램 만으로 orchestration 흐름 전달 가능.
- `_RunContext` 공유로 rag_core 코드 변경 없이 그래프 노드 교체 가능 (향후 retrieve_loop 를 streaming node 로 변경 시 rag_core phase 함수는 무변경).
- JSON-identity by construction 이므로 regression test 가 구현 오류를 잡는 게 아니라 **계약 유지** 를 잡음 — 향후 phase 함수 변경 시 두 경로 모두 자동 업데이트.

**포트폴리오 신호**: StateGraph 설계 (conditional edge, mutable shared state), phase 분리 + JSON-identity 계약, 회귀 테스트 + 성능 프로파일 분리, opt-in dep 격리.

---

## 코드 위치 레퍼런스

| 심볼 | 파일 | 설명 |
|---|---|---|
| `_RunContext` | [rag_core.py](../rag_core.py) | phase 간 공유 mutable 컨텍스트 |
| `_phase_analyze` | [rag_core.py:1204](../rag_core.py) | query 분석 + context resolution + ambiguity check |
| `_phase_retrieve_loop` | [rag_core.py:1315](../rag_core.py) | metadata-stage retry loop + verifier |
| `_phase_build_answer` | [rag_core.py:1406](../rag_core.py) | extractive answer + result dict 조립 |
| `AgenticFullState` | [rag_graph_agentic_full.py](../rag_graph_agentic_full.py) | LangGraph TypedDict state |
| `_route_after_analyze` | [rag_graph_agentic_full.py](../rag_graph_agentic_full.py) | conditional edge router |
| `_build_graph` | [rag_graph_agentic_full.py](../rag_graph_agentic_full.py) | StateGraph 빌더 (캐시됨) |
| JSON-identity 회귀 | [tests/test_langgraph_orchestrator_regression.py](../tests/test_langgraph_orchestrator_regression.py) | 계약 검증 |
| 성능 프로파일 | [tests/test_langgraph_performance_profile.py](../tests/test_langgraph_performance_profile.py) | per-node 타이밍 측정 |
