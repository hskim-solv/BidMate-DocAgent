# Observability — LangFuse / OpenTelemetry trace 백엔드

BidMate-DocAgent 는 모든 `run_rag_query` 호출에 대해 스테이지별 trace span 을
emit 하며, 단일 env var 로 게이트된다. 기본값은 오버헤드 0 의 noop 이다;
실제 백엔드(LangFuse, Honeycomb, Grafana Tempo, Datadog,
OTLP 호환 APM 무엇이든) 추가는 순수하게 환경 구성일 뿐이다.

이 페이지는
[ADR 0013](../adr/0013-observability-as-additive-pluggable-surface.md) 의
운영자용 동반 문서다.

## 아키텍처

```
                     ┌───────────────────────────────────┐
 run_rag_query ────► │ rag_observability.resolve_backend │
                     └─────────────┬─────────────────────┘
                                   ▼
                  ┌────────────────────────────────────┐
                  │ TraceBackend instance              │
                  │  • _NoneBackend  (zero overhead)   │
                  │  • _LangfuseBackend (LangFuse SDK) │
                  │  • _OtelBackend    (OTLP exporter) │
                  └─────┬──────────────────────────────┘
                        ▼
   start_trace(query, tags)
                        │
                        ▼
   _StageTimer wraps each pipeline stage with .span()
   ├─ query_analysis  (iteration=1)
   ├─ context_resolution
   ├─ query_analysis  (iteration=2)
   ├─ retrieve        (attempt_index=0, stage, top_k)
   ├─ verify          (attempt_index=0, verifier_retry)
   ├─ retrieve        (attempt_index=1, ...)            ← only on retry
   ├─ verify          (attempt_index=1, ...)
   ├─ answer_generation
   └─ synthesis       (only when prompt_profile=llm_synthesis)
                        │
                        ▼
   trace.finish(diagnostics) → trace_url (when backend supports)
                        │
                        ▼
   diagnostics.{trace_url, trace_backend, trace_unavailable_reason, trace_error}
```

trace 는 `pipeline`,
`prompt_profile`, `embedding_backend`, `retrieval_backend`,
`retrieval_mode`, `metadata_first`, `rerank`, `verifier_retry`,
`cold_start`, `query_type` 로 태깅된 하나의 루트 span 의 자식이다.
이들로 필터링 / 그룹화하는 것이 의도된 디버깅 진입점이다.

## Env vars

| Variable | Values | Default | Used by |
|----------|--------|---------|---------|
| `BIDMATE_TRACE_BACKEND` | `none`, `langfuse`, `otel` | `none` | All backends |
| `LANGFUSE_PUBLIC_KEY` | string | unset → fallback | `langfuse` |
| `LANGFUSE_SECRET_KEY` | string | unset → fallback | `langfuse` |
| `LANGFUSE_HOST` | URL | `https://cloud.langfuse.com` | `langfuse` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | URL | SDK default | `otel` |
| `OTEL_SERVICE_NAME` | string | `bidmate-docagent` | `otel` |
| `BIDMATE_TRACE_URL_TEMPLATE` | format string | unset | `otel` (optional clickable URL) |

필수 var 가 누락되면 시스템은 **fail closed** 한다 — 쿼리
동작은 `BIDMATE_TRACE_BACKEND=none` 과 동일하며,
`diagnostics.trace_unavailable_reason` 이 무엇이 누락됐는지 기록한다.

## 셋업 레시피

### LangFuse (self-hosted)

```bash
# Spin up LangFuse locally
git clone https://github.com/langfuse/langfuse
cd langfuse && docker compose up -d
# UI at http://localhost:3000 — create a project, copy the keys

pip install -r requirements-observability.txt   # or just `pip install langfuse`

export BIDMATE_TRACE_BACKEND=langfuse
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=http://localhost:3000

streamlit run demo/streamlit_app.py
# Each answer now has a "🔍 View trace" button below it.
```

### LangFuse (cloud — 일본 리전 / 한국 데이터 거주성)

Langfuse Cloud 는 US, EU, JP 리전을 제공한다. 한국 클라이언트의
데이터 거주성(data-residency) 요구사항에는 JP 리전을 사용하라.

```bash
pip install -r requirements-observability.txt

export BIDMATE_TRACE_BACKEND=langfuse
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://jp.cloud.langfuse.com   # JP region
```

또는 `.env` 에:

```
BIDMATE_TRACE_BACKEND=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://jp.cloud.langfuse.com
```

US 리전의 경우 `LANGFUSE_HOST` 를 생략한다(기본값: `https://cloud.langfuse.com`).
EU 리전: `https://eu.cloud.langfuse.com`.

### LangFuse (cloud — US, 기본값)

`docker compose up` 단계를 건너뛰고 기본
`LANGFUSE_HOST=https://cloud.langfuse.com` 를 사용한다.

### OpenTelemetry → Grafana Tempo

```bash
# Local Tempo + Grafana
docker run -d --name tempo -p 4318:4318 -p 3200:3200 grafana/tempo
docker run -d --name grafana -p 3000:3000 grafana/grafana

pip install -r requirements-observability.txt

export BIDMATE_TRACE_BACKEND=otel
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_SERVICE_NAME=bidmate-docagent
# Optional clickable URL:
export BIDMATE_TRACE_URL_TEMPLATE='http://localhost:3000/explore?orgId=1&left={"datasource":"tempo","queries":[{"query":"{trace_id}"}]}'

streamlit run demo/streamlit_app.py
```

### OpenTelemetry → Honeycomb

```bash
pip install -r requirements-observability.txt
export BIDMATE_TRACE_BACKEND=otel
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io/v1/traces
export OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<your-api-key>
export OTEL_SERVICE_NAME=bidmate-docagent
export BIDMATE_TRACE_URL_TEMPLATE='https://ui.honeycomb.io/<team>/datasets/bidmate-docagent/trace?trace_id={trace_id}'
```

### Fly.io 라이브 데모

```bash
flyctl secrets set BIDMATE_TRACE_BACKEND=langfuse
flyctl secrets set LANGFUSE_PUBLIC_KEY=pk-lf-...
flyctl secrets set LANGFUSE_SECRET_KEY=sk-lf-...
flyctl secrets set LANGFUSE_HOST=https://cloud.langfuse.com
flyctl deploy
```

## 운영

백엔드가 연결되면, 모든 CLI / Streamlit / FastAPI 쿼리는 다음을 생성한다:

- top-level 태그가 파이프라인 구성과 일치하는 루트 trace.
- 파이프라인 스테이지당 하나의 span(위 아키텍처 참조), stage-local
  속성(`attempt_index`, `verified` 등)을 포함.
- `diagnostics` 의 `trace_url` — Streamlit 에서 클릭 가능, CLI 모드에서는
  `outputs/answer.json` 에 기록, FastAPI JSON 응답에서 반환됨.

```jsonc
// diagnostics block of a tracing-enabled run
{
  "latency_ms": 18.43,
  "answer_status": "supported",
  // ... existing diagnostics keys ...
  "trace_url": "https://cloud.langfuse.com/trace/abc-123",
  "trace_backend": "langfuse",
  "trace_unavailable_reason": null,
  "trace_error": null
}
```

## 케이스 스터디 — 12분 만의 retry-rate 급증 분류(triage)

지난주 fixture smoke eval 에서 chunking-config 변경이 landing 됐다. 배포 후
LangFuse 대시보드는 **`verify` span 속성
`verifier_retry=true` 발화율이 한 시간 내에 8% 에서 31% 로 급증**한 것을
보여줬다. attempt 별 span 속성(`retrieve` span 의 `attempt_index=1`)은
이를 단일 doc 카테고리 — `procurement-IT` — 로 국소화했다. trace 의
`retrieve` span input 에서 보이는 chunk 를 읽으니 명백해졌다: 새 chunker 가
섹션 헤더를 그 내용에서 분리해, verifier 의 topic-grounding 검사가
실패하고 retry 가 발동된 것이다.

기존 diagnostics 블록만으로는 잡을 수 없었던, trace 가 표면화한 것:

1. **시계열(time-series) 형태**. retry-rate 급증이 트래픽 믹스 변화가 아니라
   배포 시각과 정확히 정렬됐다 — trace 백엔드에서만 얻을 수 있는
   그래프다.
2. **attempt 별 내비게이션**. 실패한 루트 trace 에서
   `attempt_index=1` `retrieve` span 으로 클릭해 들어가니 retry 에서 끌려온
   정확한 chunk 가 보였다. doc 카테고리는 chunk_id prefix 에서 보였다.
3. **filter-and-group 디버깅**. trace 를 루트
   `pipeline` 과 `embedding_backend` 태그로 그룹화하니 모델 변경
   가능성을 30초 만에 배제할 수 있었다(delta 가 임베딩 전반에 균일했고,
   임베딩 특정적이지 않았다).

chunker config 를 롤백하니 retry rate 가 한 시간 내에 8% 로 돌아왔다.
fix 는 trace ID 를 근거로 첨부한 follow-up 이슈로 landing 됐다.

핵심: noop 기본값과 `LANGFUSE_*` 트리플만으로, 이 디버깅 세션은 "뭔가
느려진 것 같다는 인지" 에서 "fix landing" 까지 12분이 걸렸다. trace 표면이
없었다면 같은 분류는 HEAD vs. HEAD-1 에서 eval 을 재실행하거나(느림)
쿼리별 JSON blob 을 읽는(시계열 없음) 것을 의미했을 것이다.

## Trace 예산(budget)

ADR 0013 은 tracing 이 활성화돼도 **p95 스테이지 오버헤드 < 5%** 를
약속한다. 문제가 되는 오버헤드는 `_StageTimer.__enter__` /
`__exit__` 기계와 span 별 `set_attribute` 호출이다; 네트워크
exporter 는 async 이며 카운트되지 않는다.

예산이 위반됐다고 의심된다면:

1. smoke fixture 를 `BIDMATE_TRACE_BACKEND=none` 으로 20회 실행하고,
   실행별 `stage_latency` 를 캡처해, 스테이지별 p95 를 계산한다.
2. 같은 20회를 `BIDMATE_TRACE_BACKEND=otel`(또는 `langfuse`)로 실행한다.
3. delta 가 5% 를 초과하면 `_StageTimer` 통합이
   용의자다 — 백엔드가 *아니다*(exporter 는 hot path 밖에 있다).

## 참고

- [ADR 0013](../adr/0013-observability-as-additive-pluggable-surface.md) — 결정 기록
- [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) — 병행하는 additive-ablation 선례
- [`rag_observability.py`](../../rag_observability.py) — 백엔드 레지스트리
- [`tests/test_observability_tracing.py`](../../tests/test_observability_tracing.py) — fail-closed 계약 테스트
