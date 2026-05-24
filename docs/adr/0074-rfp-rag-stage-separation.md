# 0074: RFP RAG 단계 분리 — retrieval, answer, demo default

- **Status**: proposed
- **Date**: 2026-05-24
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0002](./0002-metadata-first-retrieval.md), [ADR 0024](./0024-agentic-full-llm-as-api-default.md), [ADR 0058](./0058-phase35-mode-winner.md), [ADR 0065](./0065-metadata-routing-bounded-by-query-coverage.md), [ADR 0068](./0068-oracle-evidence-injection-ceiling-surface.md), [ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md)

## Context

ADR 0001은 `naive_baseline`을 단순 기준선으로 보존한다. 이후 ADR 0002,
0024, 0058은 metadata-first, API 기본값, hybrid retrieval을 도입했다.

각 결정은 개별적으로 타당하지만, 함께 보면 baseline, improved retrieval,
answer synthesis, agentic workflow, demo default가 한 덩어리처럼 보인다. 이는
평가 명료성을 해친다.

## Previous decision

- ADR 0002: metadata-first retrieval을 기본 검색 전략으로 표현했다.
- ADR 0024: API default preset을 `agentic_full_llm`으로 변경했다.
- ADR 0058: `agentic_full` retrieval default를 hybrid로 변경했다.

## Problem

RFP RAG에서는 다음을 분리해야 한다.

1. naive baseline은 단순하고 독립적이어야 한다.
2. retrieval 평가는 answer 평가와 분리되어야 한다.
3. evidence grounding은 reviewer가 바로 확인 가능해야 한다.
4. reranking, hybrid retrieval, metadata filtering, agents, self-correction은 명시적 후속 개선이어야 한다.
5. 구현 편의가 평가 명료성을 이겨서는 안 된다.

## Decision

RFP RAG를 다음 단계로 해석한다.

1. **Baseline stage**: `naive_baseline`은 metadata-first, hybrid, rerank, verifier retry, LLM synthesis, agent loop을 쓰지 않는다.
2. **Retrieval-improvement stage**: hybrid retrieval, metadata routing, reranking, query expansion, embedding 변경은 명시적 retrieval knob이다.
3. **Answer-evaluation stage**: verifier, refusal, synthesis, oracle evidence, LLM judge는 retrieval 개선과 별도로 평가한다.
4. **Agentic stage**: LangGraph, ReAct, planner, self-correction은 명시적 opt-in 또는 후속 stage다.
5. **Demo/API default**: API default는 제품 경험일 수 있지만 eval baseline이나 성능 근거가 아니다.

ADR 0002는 metadata-first가 전역 기본 검색 전략이라는 해석을 더 이상 유지하지
않는다. Metadata routing은 ADR 0065의 query coverage 제한 안에서만 improved
retrieval stage로 다룬다.

ADR 0024는 API default 결정으로만 유지한다. `agentic_full_llm` 기본값은 answer
synthesis 우월성의 근거가 아니다.

ADR 0058은 hybrid retrieval 채택으로 유지하되, claim-bearing eval row는 dense
control과 retrieval knob을 명시해야 한다.

## Consequences

- `naive_baseline`은 byte-identical로 유지된다.
- eval config는 조금 더 길어지지만 reviewer가 비교 조건을 바로 읽을 수 있다.
- retrieval 개선 주장과 answer 개선 주장이 분리된다.
- API default 변경이 baseline이나 retrieval 비교를 흔들지 않는다.
- metadata routing은 현실 query coverage 안에서만 해석된다.

## Files/docs/tests likely affected

- `docs/adr/0002-metadata-first-retrieval.md`
- `docs/adr/0024-agentic-full-llm-as-api-default.md`
- `docs/adr/0058-phase35-mode-winner.md`
- `docs/adr/README.md`
- `eval/config.yaml`
- `tests/test_full_dense_control_row_regression.py`
- `tests/test_api_default_pipeline_regression.py`

## Alternatives considered

- **런타임 default를 모두 dense/extractive로 즉시 되돌리기.** 기각: 본 ADR의 문제는 평가 해석의 분리다. 런타임 default 변경은 별도 측정과 별도 ADR이 필요하다.
- **기존 ADR 문맥에 맡기기.** 기각: ADR 0065, 0068, 0069가 후속 측정 표면을 세웠으므로 오래된 default 표현을 명시적으로 재해석해야 한다.
- **기존 ADR 삭제.** 기각: ADR history는 프로젝트 기록이다. 과거 결정을 삭제하지 않고 supersede/amend 관계로 남긴다.

## Verification

<!-- verifies-key: docs/adr/README.md:0074 -->
<!-- verifies-key: eval/config.yaml:full_dense -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->
<!-- verifies-key: tests/test_full_dense_control_row_regression.py:full_dense -->
<!-- verifies-key: tests/test_api_default_pipeline_regression.py:DEFAULT_API_PIPELINE -->
