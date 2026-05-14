# Agentic 정의 — bounded retry pipeline vs ReAct/Reflexion

## 한 줄 요약

BidMate-DocAgent의 "agentic"은 **metadata filter를 단계적으로 완화하는 조건부 다단계 retry 파이프라인**이다. 오픈엔드 LLM 루프(ReAct)나 자기비판 반성(Reflexion)이 아니다.

---

## 파이프라인 구조

```
[Query Analyzer]
     ↓
[metadata_stage_sequence()]     ← 최대 3단계 사전 결정
     ↓ (strict → reduced → relaxed)
[Retrieve(stage)]
     ↓
[Verifier]  → verified=True → [Answer Generator]
     ↓ verified=False
[Retry: 다음 stage로 이동]      ← MAX_AGENT_ITERATIONS = 3
     ↓ 마지막 stage 도달
[Answer Generator (allow_partial_topic=True)]
```

### 구현 위치

| 컴포넌트 | 파일 | 함수 |
|---|---|---|
| 단계 루프 | [`rag_core.py:1315`](../rag_core.py) | `_phase_retrieve_loop` |
| 단계 시퀀스 생성 | [`rag_core.py:868`](../rag_core.py) | `metadata_stage_sequence` |
| 반복 횟수 상한 | [`rag_core.py:278`](../rag_core.py) | `MAX_AGENT_ITERATIONS = 3` |
| 단계 조건 판정 | [`rag_verifier.py`](../rag_verifier.py) | `verify_evidence` |

### 단계 시퀀스 (최대 3단계)

1. **strict** — 쿼리에서 추출한 모든 metadata filter 적용 (기관명 + 날짜 + 사업번호 등)
2. **reduced** — 고신뢰 filter만 유지, 약한 constraint 제거
3. **relaxed** — metadata filter 완전 해제, pure dense/hybrid retrieval

각 단계에서 `Verifier`가 근거 충분성을 판정한다. `verified=True`이면 즉시 루프 종료 — 불필요한 추가 retrieval 없음.

---

## ReAct / Plan-and-Solve / Reflexion 비교

| 특성 | BidMate (이 시스템) | ReAct | Plan-and-Solve | Reflexion |
|---|---|---|---|---|
| **루프 구동** | 조건부 (verifier 결과) | LLM thought-action-observation | LLM이 plan 먼저 생성 | LLM 자기비판 |
| **단계 결정** | 사전 결정 (static graph) | LLM이 동적 생성 | LLM이 동적 생성 | LLM이 동적 생성 |
| **반복 상한** | 하드캡 3 (`MAX_AGENT_ITERATIONS`) | 명시적 상한 없음 | 구현별 상이 | 구현별 상이 |
| **외부 LLM 호출** | 없음 (extractive) | 매 step LLM 호출 | LLM 호출 | LLM 호출 |
| **tool 사용** | 없음 (retrieval만) | 임의 tool 선택 가능 | 임의 tool 선택 가능 | 임의 tool 선택 가능 |
| **결정론** | 완전 결정론 (동일 입력 = 동일 단계) | LLM sampling 의존 | LLM sampling 의존 | LLM sampling 의존 |
| **CI 재현성** | 완전 재현 가능 | 재현 어려움 | 재현 어려움 | 재현 어려움 |

**핵심 차이**: ReAct는 LLM이 "무슨 tool을 쓸지"를 동적으로 결정한다. BidMate는 retrieval이라는 단일 도구를 사전 정의된 stage 시퀀스에 따라 반복 호출할 뿐 — LLM이 흐름을 제어하지 않는다.

---

## 정직한 한계

- **full autonomy 없음**: tool 선택, 외부 API 호출, 웹 검색 등 열린 action space 없음
- **자기비판/반성 없음**: 이전 답변을 LLM이 평가하고 수정하는 루프 없음 (verifier는 LLM이 아닌 deterministic rule-based)
- **단일 도메인 특화**: RFP metadata structure를 전제한 stage 설계 — 범용 QA에는 적합하지 않음
- **단방향 파이프라인**: 사용자 clarification 요청, tool-calling, 대화 중 plan 수정 없음

이 한계들은 재현성·비용·hallucination 방지를 위한 의도된 trade-off이다 ([ADR 0003](../adr/0003-structured-answer-citation-contract.md), [ADR 0001](../adr/0001-preserve-naive-baseline.md)).

---

## 향후 진화 경로

| 방향 | 접근 | ADR 참고 |
|---|---|---|
| LangGraph 오케스트레이션 | 현재 stage loop → LangGraph node graph로 재구성 (이미 stage 1 완료) | [ADR 0022](../adr/0022-langgraph-orchestration-stage-1.md) |
| HyDE 쿼리 확장 | `IdentityExpander` → `HyDEExpander` opt-in (파이프라인 유지, 측정 게이트) | [ADR 0023](../adr/0023-hyde-query-expansion-ablation.md) (proposed) |
| LLM-as-reranker | `CrossEncoderReranker` → LLM 판정 reranker (additive ablation) | [ADR 0026](../adr/0026-cross-encoder-reranker-deferral.md) |
| ReAct 도입 | 현재 static stage → LLM-driven dynamic tool selection (큰 변경, 재현성 손실 감수) | 미정 — 현재는 ADR 0001 baseline 보존 우선 |

---

## 참고

- 파이프라인 실행 흐름: [`rag_core.py`](../rag_core.py) `run_rag_query` → `_phase_retrieve_loop`
- LangGraph Stage 1 case study: [`docs/agentic/agent-system-design-case-study.md`](./agent-system-design-case-study.md)
- 아키텍처 다이어그램: [`README.md § 아키텍처`](../README.md#아키텍처-요약)
