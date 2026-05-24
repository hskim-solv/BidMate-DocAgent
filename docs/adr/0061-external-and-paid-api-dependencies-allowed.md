# 0061: 외부 및 paid API 의존성 허용 (opt-in + baseline 보존 게이트)

- **Status**: proposed
- **Date**: 2026-05-20
- **Deciders**: hskim-solv
- **Related**: CLAUDE.md `## Non-goals`, ADR 0001 (naive baseline byte-identical), ADR 0005 (eval public/private split), ADR 0011 (pluggable LLM synthesis), ADR 0023 (HyDE), ADR 0017 (LLM metadata extraction)

## Context

`CLAUDE.md ## Non-goals` 가 "신규 paid-API 의존성" 을 금지해 왔다. 이 제약은
도메인 적합성이 높은 외부 옵션 — LlamaParse/Docling (한글 레이아웃 파싱),
Cohere Rerank 3.5 multilingual (`rag_rerank.py:_cohere_backend` 는 이미 배선됨),
외부 dense embedding, 강한 LLM-judge — 을 측정조차 못 하게 막아 왔다. 여러 모듈
(`rag_query_expansion.py` HyDE, `rag_synthesis.py` anthropic backend,
`rag_metadata_extraction.py` anthropic/openai backend) 이 이미 opt-in 외부 백엔드를
가지고 있어, 사실상의 정책과 명문 non-goal 사이에 드리프트가 있었다.

사용자가 이 제약을 명시적으로 완화하기로 결정했다 (2026-05-20). 단, 두 인접 제약은
독립적으로 살아 있어야 한다: (a) ADR 0001 의 baseline byte-identical 재현성,
(b) ADR 0005 의 비공개 RFP 데이터 보호. 이 ADR 은 (a)(b) 를 깨지 않으면서
외부/paid API **도입 자체**의 금지만 해제한다.

## Decision

신규 외부 및 paid API 의존성을 **opt-in 게이트 하에 허용**한다. non-goal 에서
"신규 paid-API 의존성" 줄을 제거하고, `## 핵심 원칙` 에 도입 조건을 명문화한다.

도입 조건 (3개 모두 충족해야 함):
1. **Opt-in only** — 외부 호출은 env var 또는 preset 으로만 활성화. 기본 경로는
   계속 오프라인 결정론 백엔드 (`hashing` 임베딩 / `identity` expander /
   `regex` metadata / `stub` synthesis·rerank).
2. **Baseline 보존 (ADR 0001)** — `naive_baseline` 및 CI 기본 경로는 외부 호출
   없이 byte-identical 을 유지. 외부 백엔드는 분석 변형으로만 비교에 진입.
3. **데이터 경계 (ADR 0005)** — 외부로 나가는 페이로드는 명시적 public fixture
   surface 로 제한. 이 경계는 이제 `bidmate_data_boundary.assert_external_payload_allowed`
   가 **코드로 강제**한다 (fail-closed, issue #1154): 외부 backend 진입점이 SDK
   import·네트워크 호출 **전에** 이 guard 를 호출하고, `BIDMATE_DATA_SURFACE` 가
   public fixture 로 명시 attestation 된 경우만 egress 를 허용한다 —
   unset·`private`·`local`·미인식 값은 차단되어 backend 가 오프라인 fallback
   (regex baseline / 결정론 synthesis) 으로 복귀한다. **"마스킹된 데이터" 는 아직
   sanctioned escape hatch 가 아니다**: `bidmate_security.redact_pii` 는
   phone/email/RRN 만 가리고 조달 본문(기관명·예산·사업 내용)은 그대로 남기므로
   "마스킹 후 전송" 을 신뢰 근거로 삼지 않는다. **비공개 real-eval 데이터·private
   RFP 본문의 외부 전송은 이 ADR 의 범위 밖** 이며 ADR 0005 가 계속 관할한다
   (해제하려면 별도 ADR 로 supersede + 신뢰 가능한 sanitizer 정의).

이 ADR 은 데이터 전송 정책을 바꾸지 않는다 — 오직 "외부/유료 API 를 코드/모델
레이어에 둘 수 있는가" 의 답을 No→Yes 로 바꾼다.

## Consequences

- **쉬워짐**: LlamaParse/Docling 인덱스타임 파싱, Cohere Rerank, 외부 dense
  embedding, 강한 LLM-judge (명시적 public fixture 또는 private/internal aggregate 한정) 를 ADR 게이트만 통과하면
  도입·측정 가능. 명문 정책과 기존 opt-in 백엔드 사이 드리프트 해소.
- **constrained (lock-in)**: 모든 외부 백엔드는 위 3조건을 만족해야 한다. 특히
  조건 2 가 깨지면 ADR 0001 회귀로 간주. 조건 3 위반 (비공개 데이터 외부 전송) 은
  ADR 0005 위반.
- **조건 ③ 코드 강제 (issue #1154)**: `bidmate_data_boundary` guard 가 metadata
  (`rag_metadata_extraction._anthropic_tool_use_backend`/`_openai_function_call_backend`)
  + synthesis (`rag_synthesis._anthropic_backend`/`_openai_compatible_backend`) 외부
  진입점에 적용. 기본 `BIDMATE_DATA_SURFACE` unset → fail-closed 이므로 외부 backend
  는 surface attestation 없이는 못 켜진다 (조건 ① opt-in 위에 데이터 경계 attestation
  한 겹 추가).
- **잔여 egress (follow-up, issue #1195 완료)**: metadata/synthesis 외 production
  파이프라인 외부 진입점 4곳에 동일 guard 확장 — `rag_rerank._cohere_backend`
  (`rerank:cohere`), `rag_embedding._embed_with_openai` (`embedding:openai`),
  `rag_query_expansion._call_anthropic_hyde` (`query_expansion:hyde_anthropic`),
  `rag_planner.LLMPlanner.plan_next` (`planner:anthropic`). 앞 셋 + planner 는
  never-raise 폴백이 ExternalPayloadBlocked 를 잡아 오프라인으로 복귀(rerank=원순서
  유지·hyde=원쿼리·planner=StaticPlanner)하고, openai 임베딩만 (폴백 없는 백엔드라)
  raise 로 fail-closed. **eval judges 는 의도적 제외**: ADR 0006 이 real-data judge
  egress 를 명시 허용하고 그 경계는 commit 레이어(aggregate-only, ADR 0005)가
  강제하므로, public-fixture-only egress guard 를 공유 `call_openai_json` 에 걸면
  ADR 0006 과 충돌한다 — 비공개 real-eval egress 는 본 ADR 범위 밖(위 ③)이며 ADR 0005 가 계속 관할. 오프라인
  데이터 생성 스크립트(`scripts/generate_real_cases.py` 등)도 파이프라인 egress 가
  아니라 범위 밖.
- **비용**: 외부 백엔드 활성화 시 latency·과금·가용성 의존이 생긴다. p95 budget
  (ADR 0041) 과 cost telemetry (`rag_synthesis.compute_cost_usd`) 로 관측.
- **남는 결정**: 비공개 데이터의 외부 전송을 허용할지는 미해결 — 필요 시 ADR 0005를
  supersede 하는 별도 ADR 에서 다룬다.

## Alternatives considered

- **전면 해제 (데이터 전송 포함)**: ADR 0005 를 supersede. 거부 —
  비공개 RFP 데이터 보호는 도메인 본질 제약이고, "외부 API 도입" 과 "비공개 데이터
  외부 전송" 은 분리 가능한 두 결정. one-concern 원칙상 별도 ADR 이 안전.
- **현상 유지 (non-goal 존속)**: 거부 — 이미 다수 모듈에 opt-in 외부 백엔드가
  존재해 명문 non-goal 과 코드가 모순. 사용자가 완화를 명시 결정.

## Verification

<!-- verifies-key: CLAUDE.md:외부/paid API 도입 허용 -->
<!-- verifies-key: docs/adr/0061-external-and-paid-api-dependencies-allowed.md:Opt-in only -->
<!-- verifies-key: bidmate_data_boundary.py:assert_external_payload_allowed -->
<!-- verifies-key: tests/test_external_payload_boundary_regression.py:fail_closed -->
