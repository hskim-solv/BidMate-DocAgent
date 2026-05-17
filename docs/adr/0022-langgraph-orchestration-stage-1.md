# 0022: agentic_full preset용 LangGraph orchestrator 경로 — stage 1 (passthrough) & 2 (multi-node)

- **Status**: accepted
- **Date**: 2026-05-12 (stage 1) / 2026-05-13 (stage 2)
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline은 direct-path 분석 변형으로 예약), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (agentic_full_llm은 동일 검색 표면), [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (본 ADR이 재사용하는 trace backend additivity 패턴), issue #401 (stage 1) / PR [#404](https://github.com/hskim-solv/BidMate-DocAgent/pull/404) (stage 1 구현) / issue #453 (stage 1 status flip), issue #457 (stage 2) / PR [#458](https://github.com/hskim-solv/BidMate-DocAgent/pull/458) (stage 2 구현)
- **Update (status flip, 2026-05-12, issue #453)**: Status `proposed` → `accepted`. PR [#404](https://github.com/hskim-solv/BidMate-DocAgent/pull/404) (commit `349dd08`)으로 stage-1 구현 머지 — Decision 4 항목 전부(`requirements-graph.txt`, [`rag_graph_agentic_full.py`](../../rag_graph_agentic_full.py)(`AgenticFullState` TypedDict + `run_via_langgraph` 진입점 + process-cached compiled graph), [`rag_core.py:3673-3690`](../../rag_core.py)(env-var dispatch + `_skip_graph` recursion guard + `naive_baseline` bypass), [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py)) 반영.
- **Update (stage 2 land, 2026-05-13, issue #457)**: Stage-2 multi-node 분해 머지. `rag_graph_agentic_full.py`가 3-node StateGraph(analyze / retrieve_loop / build_answer + analyze 후 conditional edge) 컴파일. `rag_core.py`는 `_RunContext` + `_build_run_context` + `_phase_analyze` / `_phase_retrieve_loop` / `_phase_build_answer`를 legacy `run_rag_query` body에서 추출 노출; direct 경로와 graph node 양쪽 동일 `_phase_*` helper 호출 → by-construction JSON-identity. 테스트에 `GraphStructureStage2Test`(3-node assertion + conditional-edge router contract + phase-helper public surface) + `test_phase_analyze_short_circuits_for_context_clarification` 추가. 기존 JSON-identity 4 테스트는 수정 없이 통과 — by-construction claim 확인.

## TL;DR

- 외부 senior review #2 ("Agentic RAG label 과장") 대응 — `run_rag_query` 내부 inner for-loop을 LangGraph StateGraph로 노출.
- Stage 1: dispatch infra + 단일 passthrough node(JSON-identity-by-construction). Stage 2: 3-node 분해(analyze/retrieve_loop/build_answer).
- `naive_baseline`은 direct path 유지(ADR 0001 불변); LangGraph는 opt-in `requirements-graph.txt`로 격리.

## 배경

외부 senior review(2026-05) finding #2가 "Agentic RAG" label 과장 지적 — 파이프라인이 procedural Python call이고 tool-call graph도, per-stage 관측 표면도 없음. agentic loop(`metadata_stage_sequence` strict → reduced → relaxed + 검증기 재시도 + answer build)는 실재하지만 *구조적으로* `rag_core.py` 426-line 단일 함수 내부 inner for-loop이며 외부 reviewer가 inspect 가능한 graph가 아님.

Plan PR-H(프로젝트 review 대응 Tier 3)가 다음 LangGraph 마이그레이션을 요청:

1. `langgraph`를 opt-in 의존성으로 추가(CI 기본은 direct 유지).
2. `agentic_full` / `agentic_full_llm` 흐름을 StateGraph로 wrap — 재시도 정책 + prompt-profile branch 가 edge로 명시.
3. `naive_baseline`은 direct path 유지 — ADR 0001 재현성 불변이 최소 분석 변형 표면에서 langgraph-import 비용을 지불하지 않음.
4. 노드가 실제로 분리되면 LangSmith / Langfuse multi-node trace 활성화(ADR 0013 backend).

어려운 부분은 JSON-identity 보장. `run_rag_query`는 cross-stage 필드 수십 개(`query_hash`, attempt index, timings, stage transition, conversation state, trace block, retrieved `chunk_ids`, claim, citation, synthesis metadata) 운반 — multi-node graph 재현 시 미세 drift 위험. `latency_ms` 순서 한 번 뒤집힘 또는 `pipeline_alias` 한 필드 회귀로 모든 eval delta 비교 + 회귀 테스트 다발이 깨질 수 있음.

## 결정 (stage 1)

**dispatch 인프라 + 단일 passthrough node를 *지금* 머지**, multi-node 분해는 stage 2로 별도 ADR 보류.

구체:

- 신규 opt-in 의존 파일 `requirements-graph.txt`에 `langgraph>=0.6,<2.0`. `requirements.txt`에는 추가 **안 함** — public CI는 langgraph import 안 함.
- 신규 모듈 `rag_graph_agentic_full.py`(root, flat-layout):
  - `AgenticFullState` `TypedDict` — 입력 + 최종 `result` dict. Stage-1 schema는 의도적 최소; stage 2에서 노드 분리에 맞춰 확장.
  - `run_via_langgraph(index, query, **kwargs) -> dict[str, Any]` — 진입점. 1-node `StateGraph` 빌드, 단일 node가 **recursion-guard kwarg `_skip_graph=True`** 로 `run_rag_query` 재호출. graph는 process-cached.
- `rag_core.run_rag_query` 상단에 env-var dispatch:
  - `BIDMATE_ORCHESTRATOR=direct`(default) — 기존 경로, 동작 불변.
  - `BIDMATE_ORCHESTRATOR=langgraph` + pipeline ≠ `naive_baseline` → `rag_graph_agentic_full.run_via_langgraph`로 위임. recursion guard는 `_skip_graph` kwarg(private, underscore-prefix, 외부 caller 없음).
  - `naive_baseline`은 env var 무관 direct 경로(ADR 0001 불변). dispatch는 `pipeline=` + `params.pipeline` 양 kwarg 형태 모두 검사.
- 신규 회귀 테스트 `tests/test_langgraph_orchestrator_regression.py`:
  - `pytest.importorskip("langgraph")`로 opt-in extra 부재 시 CI skip.
  - `(pipeline, query)` 파라미터화 — `agentic_full` / `agentic_full_llm` × 두 쿼리(single-doc + comparison) → direct vs LangGraph 경로 `json.dumps(..., sort_keys=True)` equality assertion.
  - `test_naive_baseline_skips_langgraph_dispatch`로 ADR 0001 정책 pin: `BIDMATE_ORCHESTRATOR=langgraph` 설정에도 `naive_baseline`은 direct-path 결과 반환.
  - `GraphModuleImportTest`로 모듈 public symbol + graph cache smoke.

단일 노드 passthrough가 **JSON-identity-by-construction** 보장 — 노드가 직접 direct path와 동일한 `run_rag_query` body 호출. 향후 multi-node 분해는 명시적 eval gate로 identity를 보존해야 하며, 본 ADR은 stage 1이고 그 작업을 의도적으로 연기.

## 결정 (stage 2)

passthrough 단일 노드를 legacy `run_rag_query` body 내부의 analyze / retrieve / build phase를 mirror하는 3 phase node로 분리. 핵심: 노드들이 graph 모듈에서 orchestration을 **재구현하지 않음** — 그러면 본 ADR의 two-stage split이 회피하려는 JSON-identity 회귀 위험을 그대로 안음. 대신 `rag_core.py`의 `run_rag_query` body에서 추출한 3개 private helper가 단일 출처가 되고, direct 경로 + graph node 둘 다 호출:

- `rag_core._RunContext` — 모든 cross-phase 필드(`retrieval_query`, `analysis`, `stage_sequence`, `evidence`, `verified`, `verification_reasons`, `retrieved_chunk_ids`, `plan`, trace handle, timings, ...) 운반 private mutable dataclass — 3 phase가 inline 또는 LangGraph state 스레딩 어느 쪽으로도 실행 가능.
- `rag_core._build_run_context(...)` — `params=` 묶음 정규화, 파이프라인 프리셋 해결, `_PROCESS_WARM` cold-start flag, query hashing, `query_start` log, trace backend startup을 `run_rag_query` body에서 분리. LangGraph 진입점은 graph 호출 *이전*에 이를 호출 → 3 노드가 동일 컨텍스트 공유.
- `rag_core._phase_analyze(ctx) -> dict | None` — 2회 `analyze_query` 반복 + conversation-context 해결 + 메타데이터 ambiguity / needs-clarification short-circuit 검사. short-circuit 시 최종 result dict, 아니면 `ctx` 변이 후 `None` 반환. LangGraph router(`_route_after_analyze`)가 이 신호를 읽어 conditional edge로 `END`(조기 반환) 또는 `retrieve_loop`(계속) 라우팅.
- `rag_core._phase_retrieve_loop(ctx)` — `metadata_stage_sequence` strict → reduced → relaxed 재시도 루프(`make_plan` + `retrieve` + `verify_evidence` per attempt) → `select_supporting_evidence` 적용 + `retrieved_chunk_ids` 계산.
- `rag_core._phase_build_answer(ctx) -> dict` — `generate_answer`(`agentic_full_llm` 시 `synthesize_answer` 추가) 실행, conversation state 갱신, legacy body와 동일 key 순서로 `diagnostics` + 최종 `result` dict 조립, trace diagnostics 부착, `query_complete` log 출력.

신규 `run_rag_query` body:

```python
ctx = _build_run_context(...)
early_result = _phase_analyze(ctx)
if early_result is not None:
    return early_result
_phase_retrieve_loop(ctx)
return _phase_build_answer(ctx)
```

LangGraph 노드는 동일 3 phase 호출의 얇은 wrapper. JSON-identity는 by construction 보존 — phase 함수가 legacy body의 이동된 블록을 동일 순서·동일 입력으로 실행. 회귀 테스트 `tests/test_langgraph_orchestrator_regression.py`(`BIDMATE_ORCHESTRATOR=direct` vs `=langgraph`, 2 쿼리 × 2 프리셋의 `json.dumps(..., sort_keys=True)` byte-equality 비교)는 수정 없이 통과.

`AgenticFullState`는 stage 1에서 작은 TypedDict(`index`, `query`, `pipeline_kwargs`, `result`); stage 2는 그 필드를 단일 mutable `ctx` slot + 동일 terminal `result` slot으로 교체. 중간 필드는 `_RunContext`에 거주 → orchestration이 명시화되어도 TypedDict는 최소 유지.

stage-1 recursion guard(`_skip_graph` kwarg)는 correctness상 더 이상 불필요 — stage 2 노드는 `_phase_*` 직접 호출, `run_rag_query`로 되돌아오지 않음 — 그러나 환경 변수 독립 deterministic dispatch가 필요한 caller를 위해 private "force direct path" override로 유지.

stage-2 전용 테스트 추가:

- `GraphStructureStage2Test.test_graph_has_three_phase_nodes` — compiled graph가 `analyze` / `retrieve_loop` / `build_answer` 운반 pin → 향후 refactor가 passthrough로 silently collapse 불가.
- `GraphStructureStage2Test.test_route_after_analyze_branches_on_result_presence` — conditional-edge 계약 pin: `result` 존재 ⇒ END, 그 외 ⇒ `retrieve_loop`.
- `GraphStructureStage2Test.test_phase_helpers_exposed_from_rag_core` — `rag_core`가 `_build_run_context`, `_phase_analyze`, `_phase_retrieve_loop`, `_phase_build_answer`를 계속 노출; rename은 first dispatch가 아닌 여기서 표면화.
- `test_phase_analyze_short_circuits_for_context_clarification` — phase가 어느 경로(short-circuit / 계속)를 타든 다음 phase 또는 caller가 기대하는 계약과 일치하는 state 인계.

## 결과

쉬워진 점:

- "Agentic RAG" label이 코드와 일치하는 구체적 운영 의미 획득: `BIDMATE_ORCHESTRATOR=langgraph`는 이제 3-node StateGraph 실행(1-node passthrough 아님) — 각 노드 inspect 가능, LangSmith / Langfuse per-stage latency가 3 phase에 깔끔히 매핑.
- orchestration 단일 출처: `_phase_*` helper가 direct 경로든 graph 경로든 동일 실행 → drift 불가.
- 위험한 JSON-identity 작업은 stage 1의 dispatch + harness 범위로 한정; stage 2는 회귀 테스트 계약에 0 변경.
- `naive_baseline` ADR 0001 불변이 doc convention이 아니라 명시 테스트로 pin.

비용 / 정직:

- `_RunContext`는 30+ 필드 private dataclass — 크지만 각 필드는 legacy body가 이미 local 변수로 운반하던 것. cross-phase 계약을 함수-scoped local의 *암묵*이 아니라 *명시*로 만듦.
- LangGraph 버전 범위(`>=0.6,<2.0`) 넓음. LangGraph 2.x breaking API 시 `_build_graph`의 dispatch table + conditional-edge 호출 site만 재pin.
- `_skip_graph` kwarg는 soft override(stage 1은 recursion safety용; stage 2는 불필요). 제거는 후속 cleanup.
- phase helper는 private(`_`-prefix). 외부 코드가 phase-level surface 원하면 internal 계약 의존 대신 후속 ADR로 public API 요청.

## 검토한 대안

- **stage 1 skip, multi-node 분해 전체 ship.** 기각: `run_rag_query` ~426-line 출력 조립에 대한 JSON-identity 회귀 위험 실재 + 기존 650+ 회귀 테스트 깨지면 설계가 아니라 디버깅으로 PR이 막힘. 분할로 위험 한정.
- **`langgraph`를 `requirements.txt`(always-on)로.** 기각: langgraph + 의존 트리(`langchain-core`, `pydantic`, ...)가 stage 1의 순수 passthrough 위해 모든 CI install / Docker image 팽창. ADR 0011 / ADR 0013 "additive opt-in" 패턴 = opt-in extra는 자체 requirements 파일.
- **`_skip_graph` kwarg 대신 thread-local recursion guard.** 기각: thread-local은 call site에서 invisible(caller가 계약 확인 불가). private kwarg는 명시 + 테스트 가능.
- **`naive_baseline`도 LangGraph로 마이그레이션.** ADR 0001 기각 — 최소 분석 변형 표면이 opt-in extra에 의존 불가. LangGraph 의존 부재여도 `naive_baseline` 실행 필수.

## See also

- [`rag_graph_agentic_full.py`](../../rag_graph_agentic_full.py) — stage-2 3-node graph 모듈(analyze / retrieve_loop / build_answer + conditional edge).
- [`rag_core.py`](../../rag_core.py) — `_RunContext`, `_build_run_context`, direct 경로 + LangGraph 노드 양쪽 호출 `_phase_*` helper.
- [`requirements-graph.txt`](../../requirements-graph.txt) — opt-in LangGraph 의존.
- [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py) — JSON-identity + ADR-0001 dispatch 테스트(stage 1) + multi-node graph 구조 테스트(stage 2).
- [ADR 0001](./0001-preserve-naive-baseline.md) — 본 ADR이 명시 보존하는 naive_baseline 정책.
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) — 본 ADR이 재사용하는 additive opt-in 패턴.
- [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) — trace backend additivity 패턴; LangSmith / Langfuse per-stage latency가 stage-2 3 노드에 깔끔 매핑.
