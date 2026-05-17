# 0013: 관측성을 추가·pluggable·fail-closed 표면으로

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) 확장; [ADR 0003](./0003-structured-answer-citation-contract.md) 보존; [ADR 0006](./0006-llm-judge-on-real-data-only.md), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 백엔드 패턴 재사용; [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) eval 분리 존중; [ADR 0020](./0020-protocol-based-pluggability.md) (검색 측 Protocol) 와 같은 "추가 pluggable 표면" 테마
- **Deciders**: hskim

## TL;DR

- 트레이스 viewer (LangFuse / OTel) 를 pluggable 백엔드 레지스트리로 추가 — `BIDMATE_TRACE_BACKEND=none` 기본은 noop.
- 어떤 관측성 실패도 쿼리 경로를 깨지 못함 (fail-closed) — 모든 backend boundary 에서 예외 catch + noop 폴백.
- `schema_version` bump 안 함; 트레이스 데이터는 `diagnostics` 에 거주, `answer` 계약 미변경.

## 배경

[`rag_core.py`](../../rag_core.py) 는 이미 `_StageTimer` context manager 로 단계별 타이밍 누적 + `diagnostics.stage_latency` 노출. ADR 0011 가 `diagnostics.synthesis.{backend, model, tokens_in, tokens_out, latency_ms, fallback_reason}` 추가. 빠진 것은 **sink** — reviewer (또는 on-call 엔지니어) 가 쿼리별 단계 breakdown, 토큰 수, 비용 추세, 실패 모드율을 시간 축으로 볼 수 있는 트레이스 viewer.

Applied AI / LLM Ops 포트폴리오에서 트레이스 viewer 는 최고 레버리지 관측성 신호 — "답변 반환" 과 "프로덕션 운용 가능" 의 차이. 통합 shape 가 특정 vendor 보다 중요 — LangFuse, Honeycomb, Datadog, Grafana Tempo, 모든 OTLP 호환 백엔드가 파이프라인 손 안 대고 동작해야.

트레이싱을 `run_rag_query` 에 직접 묶으면 ADR 0001 기준선 보존 충돌 (noop 기본은 결정론·무료 필요) + ADR 0005 eval 분리 위험 (exporter 크래시가 CI 실패 유발). 올바른 수는 ADR 0011 의 LLM 합성 방어 형태 — **파이프라인 동작 손 대지 말고 관측성을 추가·pluggable·fail-closed 표면으로 추가.**

## 결정

관측성은 [`rag_observability.py`](../../rag_observability.py) 의 pluggable 백엔드 레지스트리로 노출되는 *추가* 표면, `BIDMATE_TRACE_BACKEND` gate. 구체적으로:

- 기본 `BIDMATE_TRACE_BACKEND=none` 은 `span()` 이 `contextlib.nullcontext()` 반환하는 noop `TraceContext` 실행; 파이프라인 동작이 본 모듈 없는 빌드와 byte-identical.
- [`rag_core.py`](../../rag_core.py) 의 `_StageTimer` 가 선택적 `trace=` kwarg 수용. non-noop 시 각 타이밍 region 이 트레이스에 자식 span 도 오픈.
- 백엔드 레지스트리 `_BACKENDS = {"none": ..., "langfuse": ..., "otel": ...}` 가 [ADR 0011 합성 레지스트리](../../rag_synthesis.py) 미러링. 새 백엔드 추가는 factory 등록만 — `run_rag_query` 편집 불필요.
- `run_rag_query` 가 새 진단 키 4개 노출: `trace_url`, `trace_backend`, `trace_unavailable_reason`, `trace_error`. ADR 0003 답변 계약 일부 아님 — `answer` 가 아닌 `diagnostics` 에 거주. `schema_version` **bump 안 함**.

### Span topology

`run_rag_query` 호출 1회가 다음 자식 span 들과 함께 root 트레이스 1개 emit:

| Span 명 | 카디널리티 | 속성 |
|-----------|-------------|------------|
| `query_analysis` | 2 (context resolution 전·후) | `iteration ∈ {1, 2}` |
| `context_resolution` | 1 | — |
| `retrieve` | N (재시도 1회당) | `attempt_index`, `stage`, `top_k` |
| `verify` | N (재시도 1회당) | `attempt_index`, `verifier_retry` |
| `answer_generation` | 1 | — |
| `synthesis` | 0 또는 1 (`prompt_profile=llm_synthesis` 만) | `prompt_profile` |

Root 트레이스 태그: `pipeline`, `prompt_profile`, `embedding_backend`, `retrieval_backend`, `retrieval_mode`, `metadata_first`, `rerank`, `verifier_retry`, `cold_start`, `query_type`. reviewer 가 트레이스를 필터·그룹화할 컬럼들.

### 백엔드 pluggability

- `none` (기본) — `_NoopTraceContext`. 오버헤드 0. `make smoke`, `pr-eval.yml`, 공개 CI, 오프라인 데모 실행하는 reviewer 가 사용.
- `langfuse` — `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` 필요; 선택적 `LANGFUSE_HOST` (기본 `https://cloud.langfuse.com`). 백엔드 factory 내부에서 `langfuse` 패키지 lazy import — dependency 누락 시 `trace_unavailable_reason=missing_dependency:langfuse` 로 noop 폴백. 트레이스 URL 은 `trace.get_trace_url()` 통해 `diagnostics.trace_url` 에 노출.
- `otel` — 표준 OpenTelemetry SDK. SDK 컨벤션대로 `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` 따름. 선택적 `BIDMATE_TRACE_URL_TEMPLATE` (예: `https://ui.honeycomb.io/.../trace?trace_id={trace_id}`) 가 opaque OTLP trace_id 에서 클릭 가능 URL 렌더.

### Fail-closed 계약

본 표면의 정의 속성은 *어떤 관측성 실패도 쿼리 경로를 깰 수 없음*. 모든 backend boundary 가 예외 catch + noop 폴백:

| 실패 | 동작 |
|---------|----------|
| 선택 dep 누락 | `trace_backend=none`, `trace_unavailable_reason="missing_dependency:<pkg>"` |
| 자격 누락 | `trace_backend=none`, `trace_unavailable_reason="missing_credentials:<backend>"` |
| 백엔드 생성자 raise | `trace_backend=none`, `trace_unavailable_reason="backend_init_error:..."` |
| `start_trace` raise | `trace_backend=<requested>`, `trace_url=None`, `trace_error="start_trace:..."` |
| 파이프라인 중간 `span()` raise | `_StageTimer.__exit__` 가 swallow; 파이프라인 계속; 후속 span 도 시도 |
| `finish()` raise | `trace_url=None`, `trace_error="finish:..."` |

**추가 분석 변형 불변식** (ADR 0001 / ADR 0011 을 여기 적용): 어떤 실패 모드 주입 시에도 결과가 (`trace_*` 키와 변동 타이밍 strip 후) noop run 과 byte-identical. [`tests/test_observability_tracing.py`](../../tests/test_observability_tracing.py) 의 `test_start_trace_exception_falls_back` 에 lock.

### 주기

- **공개 합성 CI** (`pr-eval.yml`): `BIDMATE_TRACE_BACKEND` unset → noop. SDK 설치 없음. 파이프라인 동작 불변.
- **실데이터 eval**: 선택. noop 기본. reviewer 가 `BIDMATE_TRACE_BACKEND=langfuse` 로 일회성 디버깅 opt-in 가능 — ADR 0005 commit 경계 영향 없음 (집계 메트릭 불변; 쿼리별 트레이스만 export).
- **라이브 데모**: Fly.io secret 통해 `BIDMATE_TRACE_BACKEND=langfuse` 구성. Streamlit 데모가 각 답변 하단에 "View trace" 링크 노출 (이슈 acceptance 기준).

## 결과

**Wins**

- 시스템이 ADR 0001 (기준선) / ADR 0003 (답변 계약) 위험 없이 프로덕션급 관측성 표면 (단계별 span, 재시도 루프 가시성, 토큰 수, 비용 추세) 획득.
- vendor 중립 백엔드 2종 (LangFuse 네이티브 UX, OTel 모든 APM) + 결정론 noop 기본. Honeycomb, Datadog, Grafana Tempo 추가는 환경 설정이지 코드 변경 아님.
- ADR 0006/0007 백엔드 레지스트리 관용구 재사용 → 코드베이스에 "pluggable 백엔드 추가 방법" 일관 패턴 (평가자 → 합성 → 트레이스).
- 재시도 루프 가시성 (`attempt_index` 속성의 `retrieve` / `verify` 자식 span 시퀀스) 이 #69 같은 부분 grounding 케이스 디버깅에 진정 유용 — 역사적으로 `stage_attempts` 요약뿐, 이제 span 시퀀스로 추적.

**Costs**

- 선택 dependency 3개 (`langfuse`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`). 모두 백엔드 factory 내부 lazy import 뒤. `BIDMATE_TRACE_BACKEND` 가 사용하는 백엔드로 설정 안 되면 런타임 필요 없음.
- `_StageTimer.__enter__` / `__exit__` 에 `trace=None` 시에도 작은 오버헤드 (단계당 `None`-check 1회). smoke fixture 쿼리당 < 0.1ms 측정, 아래 트레이스 budget 제약 내.
- 새 모듈 + 새 env-var family 1개. 기본이 `none` (오프라인·세팅 없음) 으로 완화.

**Constraints (불변)**

- ADR 0001: `naive_baseline` 가 본 모듈 유·무와 상관없이 동일 실행. `pipeline_cli_choices()` 불변.
- ADR 0003: `schema_version: 2`, `status` 값, `claims[].citations`, `evidence[]` 불변. 트레이스 데이터는 `answer` 가 아닌 `diagnostics` 에 거주.
- ADR 0005: 실데이터 케이스별 트레이스는 로컬 (reviewer 가 고른 LangFuse host). 공개 CI 트레이싱은 noop. 집계 메트릭 무영향.
- ADR 0011: `diagnostics.synthesis` 키 유지. 새 `synthesis` span 은 LLM 합성 실행 시만 오픈.

### 트레이스 budget

트레이싱 enable 시에도 단계당 p95 오버헤드가 noop 기준선 대비 **5%** 이내. span 머신 자체 비용 (네트워크 exporter 는 비동기이므로 제외) bound. budget 초과 시 어떤 백엔드 탓 전에 `_StageTimer` 통합부터 재검토.

## 검토한 대안

- **트레이싱을 `run_rag_query` 에 직접 묶기.** Reject: 관심사 결합, 파이프라인 가독성 저해, "파이프라인이 하는 일" 과 "관측 방식" 코드 conflate. 두 번째 백엔드 추가가 레지스트리 편집 아닌 `run_rag_query` 편집 됨.
- **print-only 로깅.** Reject: 시계열 없음, 단계별 span 탐색 없음, 토큰·비용 대시보드 없음. 로컬 디버깅엔 유용하나 LLM Ops 포트폴리오 신호 미달.
- **Always-on 트레이싱.** Reject: ADR 0005 위반 (공개 CI 는 결정론·네트워크 dep 없음). smoke 테스트도 brittle 화.
- **wrap-only 외부 span (쿼리당 span 1개, 자식 없음).** Reject: 디버깅 가치 대부분이 단계별 breakdown — `verify` 가 병목인지 `retrieve` 가 재시도 유발인지 아는 게 N ms 총합보다 actionable.
- **백엔드 1개만 (LangFuse only).** Reject: LangFuse 가 AI 네이티브 UX 엔 좋지만 enterprise 는 Honeycomb / Datadog / Grafana Tempo 기존 보유 빈번. OTel 이 동일 instrumentation 을 코드 비용 0 으로 어디든 보냄.
