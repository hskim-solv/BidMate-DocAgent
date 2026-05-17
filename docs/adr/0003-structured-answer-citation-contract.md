# 0003: 구조화된 답변/인용 계약 (`schema_version: 2`)

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`docs/agentic/answer-policy.md`](../agentic/answer-policy.md) (working reference, 강제 walkthrough 는 [§계약 강제 메커니즘](../agentic/answer-policy.md#계약-강제-메커니즘)), [`docs/eval/citation-grounding-eval.md`](../eval/citation-grounding-eval.md), [`docs/agentic/verifier-rules.md`](../agentic/verifier-rules.md) (deterministic verifier rules as pseudo-prompts; status / citation mapping table), [`eval/run_eval.py`](../../eval/run_eval.py)

## TL;DR

- 모든 답변은 `schema_version: 2` JSON 객체 — `status`/`claims`/`evidence`/`status_reason` 구조화.
- 보류(`insufficient`)는 일급 신호이지 빈 답이 아님.
- `answer_text` 는 사람용 요약일 뿐 계약 외 — 툴링은 키오프 금지.

## 배경

근거 기반 RAG 의 신뢰도는 인용 품질에 비례한다. 초기엔 "(see chunk 3)" 같은 비정형 참조의 free-text 답변이었다 — demo 엔 OK, 평가엔 무용. 인용 정밀도·주장 정합·올바른 보류 등 측정 대상마다 heuristic 파싱이 필요해 모든 지표가 brittle, 모든 회귀가 invisible 했다.

또한 *"근거 없음"* 을 그럴듯한 환각 없이 표현하는 명확한 수단이 필요하다. 그 신호는 텍스트 부재가 아니라 응답의 값이어야 — 호출자가 programmatic 으로 처리 가능해야 한다.

## 결정

모든 답변은 `schema_version: 2` JSON 객체. 계약:

- `status` ∈ {`supported`, `partial`, `insufficient`}. 다른 값 불허
- `claims` 는 `{target, claim, support, citations[]}` 리스트. 각 `citation` 은 top-level `evidence` 리스트로 back-pointing 하는 `doc_id`·`chunk_id` 보유. 이게 없으면 주장은 구조상 unsupported
- `status_reason` 은 기계 판독 가능: `{code, verified, verification_reasons[]}`. eval 파이프라인이 이를 키로 사용
- top-level `evidence` 는 실제 retrieved chunk 보유 — `doc_id`·`chunk_id`·`text` + 해결에 쓰인 메타데이터. citation 은 이 리스트로 resolve
- `answer_text` 는 사람용 요약. 계약 일부 **아님** — 툴링이 키오프 금지
- insufficient 답변은 fake 답변 대신 `missing_targets` + 사람용 메시지를 담는 `insufficiency` 블록 보유

[`docs/agentic/answer-policy.md`](../agentic/answer-policy.md) 가 working reference; 이 ADR 이 load-bearing 결정.

## 결과

**Wins**

- eval 지표(`citation_grounding`·`claim_citation_alignment`·`answer_format_compliance`)를 기계 계산 가능 — `reports/eval_summary.json` 숫자가 best-effort 가 아닌 실측
- API demo 는 `run_rag_query` dict 를 verbatim 반환 가능(FastAPI 표면과 ADR-aligned) — 응답이 곧 계약이기 때문
- 보류가 일급 신호화. issue #69 의 partial-topic grounding 작업이 `partial` vs `insufficient` 결정을 둘 곳을 확보

**Costs**

- 답변에 손대는 모든 동작 변경이 이 계약 위반 여부 검토 필요. `schema_version` bump 는 정확히 호환 깨짐을 명시화하기 위해 존재
- free-text-only 모델은 이 shape 을 emit 하는 wrapper 없이 drop-in 불가

## 검토한 대안

- **regex 로 파싱하는 inline 인용 free-text 답변.** Reject: 모든 지표 brittle, 모든 리뷰어 inspection 수동
- **generic LangChain / agent-framework 응답 모델 사용.** Reject: 외부 일정에 묶임, eval delta job 의미 보전 위해 stability 필요
