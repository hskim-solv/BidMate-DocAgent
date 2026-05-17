# 0042: Tool-use 근거 경계 방어

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0008](./0008-evidence-boundary.md) (근거-측 방어),
  [ADR 0040](./0040-react-agent-loop-additive-preset.md) (ReAct 프리셋),
  [ADR 0003](./0003-structured-answer-citation-contract.md) (답변 계약),
  issue #682

## TL;DR

- ReAct 도구 → LLM 경계에서 근거 텍스트가 prompt-override 명령을 우회할 위험 audit
- 기존 ADR 0008 `neutralize_instruction_patterns` 적용 범위가 도구 표면에도 충분함을 확인
- 향후 `execute_*` 추가 시 외부 텍스트 포함하면 neutralize 호출 의무화

## 배경

ADR 0008 은 답변 생성 단계에서 LLM 에 도달하기 전 검색된 근거 텍스트를 정제하는 `neutralize_instruction_patterns` 를 도입했다. 공격 표면은: 적대적 문서가 prompt-override 명령 (예: `\n\nHuman:` 채팅 토큰, `IGNORE PREVIOUS INSTRUCTIONS`) 을 텍스트에 심으면 LLM prompt 에 그대로 주입되는 것.

ReAct agent 루프 (ADR 0040) 는 ADR 0008 이 다루지 않는 **새 공격 표면** 을 연다: `rag_agent_tools.py` 의 네 `execute_*` 도구 래퍼 함수가 반환하는 dict 의 문자열 값이 직렬화되어 다음 multi-turn LLM 메시지에 삽입된다. 검색된 청크가 주입된 명령을 포함하면 명시 neutralize 없이는 다음 planning 턴 user 메시지로 살아남는다.

기존 `neutralize_instruction_patterns` (ADR 0008) 가 정식 방어. 본 ADR 은 도구 → LLM 경계를 넘는 모든 텍스트에 이를 적용함을 의무화한다.

## 결정

**`rag_agent_tools.py` 의 모든 `execute_*` 함수 중 검색된 근거에서 파생된 텍스트를 반환하는 것은 반환 dict 에 포함하기 전 `neutralize_instruction_patterns` 를 적용해야 한다.**

세부:
- `execute_retrieve_evidence`: `meta` dict 는 진단용 (근거 텍스트 아님) — 이 레벨에서 neutralize 불필요. `retrieve_candidates` / `verify_evidence` 내부에서 근거 텍스트에 적용 (기존 ADR 0008 커버리지)
- `execute_verify_grounding`: `reasons` 는 내부 생성 문자열 (외부 근거 텍스트 아님) — neutralize 불필요. 근거 텍스트는 `verify_evidence` 내부에서 neutralize (ADR 0008)
- `execute_expand_query_hyde`: 확장 쿼리는 LLM 생성 (검색 근거 아님) — neutralize 불필요
- `execute_abstain`: `reason` 문자열은 LLM 자체 출처 — 외부 텍스트가 이 경계를 넘지 않음
- `format_verifier_feedback` (PR-D): reasons 는 내부 생성 — neutralize 불필요

**Net 결과**: `verify_evidence` 내부의 기존 ADR 0008 커버리지가 현재 설계의 도구 표면에 충분하다. 본 ADR 은 audit 을 공식화하고 추가 call site 가 필요 없음을 확인한다.

**회귀 게이트 (PR-E)**:
`tests/test_agent_react_regression.py` 가 `format_verifier_feedback` 출력과 `execute_abstain` 반환값에 `EVIDENCE_BOUNDARY` sentinel 이 없고, `AGENT_REACT_SYSTEM_PROMPT` 가 근거 텍스트를 echo 하지 않음을 확인한다.

## 결과

### 긍정

- 도구 사용 공격 표면 명시 audit — ADR 0008 커버리지가 추가 코드 변경 없이 ReAct 루프로 확장됨 확인
- 회귀 테스트로 audit machine-checkable
- 향후 `execute_*` 추가 시 규칙 문서화: 반환값에 외부 텍스트 포함하는 래퍼는 그 텍스트에 `neutralize_instruction_patterns` 호출

### 부정 / 트레이드오프

- 없음: audit 결과 갭 0 이므로 성능 오버헤드 추가 없음

## 향후 `execute_*` 추가 규칙

> **반환값이 검색된 문서 또는 사용자 제출 콘텐츠 (내부 생성 아닌) 의 텍스트를 포함하면 반환 전 `neutralize_instruction_patterns` 를 적용한다.**

`EVIDENCE_BOUNDARY` 회귀 테스트는 새 함수 출력을 포함하도록 업데이트해야 한다.
