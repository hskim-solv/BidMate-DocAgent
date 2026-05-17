# 0020: 검색 측 확장 포인트의 Protocol 기반 pluggability

- **Status**: accepted
- **Date**: 2026-05-13
- **Related**: [ADR 0013](0013-observability-as-additive-pluggable-surface.md) (추가 pluggability 테마), [PR #234](https://github.com/hskim-solv/BidMate-DocAgent/pull/234) (VectorStore Stage 1), [PR #358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358) (Reranker), [issue #176](https://github.com/hskim-solv/BidMate-DocAgent/issues/176) (VectorStore 작업), [issue #345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345) (Reranker 작업), [`rag_vector_store.py`](../../rag_vector_store.py), [`rag_reranker.py`](../../rag_reranker.py)

## TL;DR

- Phase 2 의 VectorStore + Reranker 리팩터가 같은 4-속성 패턴 (Protocol + 기본 어댑터 + factory + env-var 라우팅) 으로 우연 수렴.
- 본 ADR 이 그 컨벤션을 명시화 → 미래 검색 측 확장 포인트 (QueryExpander, EmbeddingBackend) 가 재논쟁 없이 동일 4단계 따름.
- 기본 어댑터가 기존 코드 경로 wrap → 머지 시 eval 영향 없음 (ADR 0001 불변식).

## 배경

독립 Phase 2 리팩터 2개가 공유 아키텍처 근거 없이 구조적으로 동일한 패턴 도입:

**VectorStore Protocol** (이슈 #176, PR #234 + 후속 #288 / #296 / #326):
`rag_vector_store.py` 가 `@runtime_checkable typing.Protocol` (VectorStore) 노출 + `InMemoryVectorStore` 기본 + `QdrantVectorStore` 어댑터. `BIDMATE_INDEX_BACKEND` 가 dispatch 구동; 새 백엔드 등록 시 `rag_core.py` 미접촉.

**Reranker Protocol** (이슈 #345, PR #358):
`rag_reranker.py` 가 동일 shape 미러링 — `@runtime_checkable` Protocol, `rag_rerank.rerank` wrap 하는 `CrossEncoderReranker` 기본 어댑터, 단일 wiring 훅으로 `default_reranker()` factory. 미래 reranker (HyDE, LLM-as-judge) 가 여기 플러그; `rag_core.py` 미접촉.

컨벤션이 Phase 3 (HyDE 쿼리 확장, 대체 임베딩 백엔드, multi-query 검색) 에서 자연 재발. 작성된 ADR 없으면 미래 모든 Protocol PR 이 동일 설계 질문 재논쟁: ABC vs Protocol, factory vs 직접 import, env-var vs plan-dict 라우팅.

[`docs/adr/README.md`](README.md) 의 ADR 임계: *"미래 변경이 따라야 할 새 컨벤션 확립."* 양 PR 이미 머지; 본 ADR 이 묵시 컨벤션을 명시 참조로 전환.

## 결정

검색 측 확장 포인트는 4-속성 컨벤션 따름:

1. **leaf 모듈의 `@runtime_checkable typing.Protocol`.**
   Protocol 이 자기 파일 (`rag_<aspect>.py`) 거주 → dependency graph 가 acyclic 유지. `runtime_checkable` 가 구체 타입 결합 없이 테스트에서 `isinstance` 가드 가능.

2. **기본 어댑터가 기존 구현 wrap.**
   새 모듈의 첫 구체 클래스 (`InMemoryVectorStore`, `CrossEncoderReranker`) 가 기존 코드 경로에 위임 → 관찰 가능 동작 bit-identical 유지. 머지 시 eval 회귀 없음.

3. **단일 dispatch 훅으로 `default_<aspect>()` factory.**
   orchestration 코드 (`rag_core.py`, `rag_retrieval.py`) 가 `default_reranker()` / `default_vector_store()` 정확히 1회 호출. 두 번째 구현 추가는 한 파일 한 함수 변경; 검색 orchestration 미접촉.

4. **factory 내부 env-var 라우팅; plan-dict 라우팅은 범위 외.**
   `BIDMATE_INDEX_BACKEND`, `BIDMATE_RERANK_BACKEND` 가 dispatch 신호. `analyze_query` 가 만드는 plan dict 는 쿼리 레벨 결정용; 백엔드 선택은 환경 레벨 설정.

## 결과

**Easier:**
- 새 확장 포인트 (예: `QueryExpander`, `EmbeddingBackend`) 가 같은 4 단계 따름. PR reviewer 가 패턴 재검토 대신 본 ADR 인용 가능.
- `isinstance(x, VectorStore)` 와 `isinstance(x, Reranker)` 가 구조적 duck-typing 체크 테스트에서 동작.
- 머지 시 eval 무영향: 기본 어댑터가 기존 코드 경로 wrap → `naive_baseline` bit-identical (ADR 0001 불변식).

**Harder / constrained:**
- ceremony 비용: 새 검색 측 확장 포인트가 새 함수 아닌 새 leaf 모듈 (Protocol + 기본 클래스 + factory) 요구. 되돌림 비용 낮음 — 각 leaf 모듈 독립.
- `@runtime_checkable` Protocol 이 `isinstance` 시 메서드 시그너처 미체크, 존재만 체크. 완전 타입 안전은 런타임 가드 단독 아닌 `mypy` 구조 체크 필요.

**이미 설정된 follow-up 선례:**
- `rag_query_expansion.py` (ADR 0023) 가 같은 4-속성 컨벤션으로 `QueryExpander` 도입 + 본 패턴 인용.
- Phase 3 HyDE, LLM-as-reranker, 대체 임베딩 백엔드가 같은 shape 따를 예정.

## 검토한 대안

- **Protocol 대신 ABC (`abc.ABC` + `@abstractmethod`)**: ABC 는 구체 클래스가 register 또는 inherit 필요 → 확장 포인트를 base 클래스와 결합. Protocol 은 구조 동작 — 옳은 메서드 가진 어떤 클래스든 본 모듈에서 import 안 하고 계약 충족. 선택: Protocol.

- **Factory 없는 직접 import**: caller 가 구체 클래스 직접 import. Reject: 기본 클래스 변경 시 orchestration 코드 import site 변경. factory 패턴 (1 import, 1 call site) 이 미래 swap 투명 처리.

- **Plan-dict 라우팅**: 쿼리 분석 plan dict 가 요청당 백엔드 선택. 백엔드 선택엔 reject: 백엔드는 쿼리당 결정 아닌 환경 레벨 설정 (비용, 가용성). Plan-dict 라우팅은 *검색 모드* (flat vs hierarchical, ADR 0002) 엔 옳으나 *인프라 wiring* 엔 아님.
