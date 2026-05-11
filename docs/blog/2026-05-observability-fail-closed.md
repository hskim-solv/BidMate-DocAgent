---
layout: page
title: Observability를 baseline 깨지 않고 추가하는 패턴
date: 2026-05-12
permalink: /blog/2026-05-observability-fail-closed/
---

> 결론: trace 백엔드는 *추가*되는 surface일 뿐, 파이프라인 행동을 바꾸면 안 된다.
> 결정적 noop default + lazy import + fail-closed 예외 처리 — 세 장치를 동시에 거는 한 가지 패턴으로 LangFuse, OTel, 미래의 어떤 백엔드도 같은 모양으로 들어온다.

## 왜 이 결정이 필요했는가

BidMate-DocAgent는 retrieval → verifier → grounded answer 파이프라인이다. [`rag_core.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_core.py)는 이미 `_StageTimer` 컨텍스트 매니저로 stage별 latency를 모으고 `diagnostics.stage_latency`에 노출한다. ADR 0011 LLM 합성은 `diagnostics.synthesis.{tokens_in, tokens_out, latency_ms}` 까지 더했다.

부족한 건 **sink** — 리뷰어나 on-call 엔지니어가 query별 stage 분해, 토큰 수, retry 패턴, 실패 모드를 *시간 축으로* 볼 수 있는 trace viewer다. Applied AI / LLM Ops 포트폴리오에서 trace viewer는 가장 결정적인 운영 시그널이다. "답변을 반환한다" 와 "production에서 운영할 수 있다" 사이의 차이가 여기서 생긴다.

## 순진한 접근: pipeline에 직접 bundle

가장 간단한 방법은 `run_rag_query` 안에 LangFuse SDK를 직접 호출하는 것이다.

```python
def run_rag_query(query, ...):
    with langfuse.trace(name="rag_query") as t:
        with t.span("retrieve"):
            ...
        with t.span("verify"):
            ...
```

이걸 채택하지 않은 이유는 세 가지 ADR 위반이다:

1. **ADR 0001 (baseline 보존)**: `naive_baseline` 호출이 LangFuse 네트워크 의존성을 갖게 된다. CI 결정성과 offline 재현성이 모두 깨진다.
2. **ADR 0005 (eval split)**: exporter 한 번 죽으면 public CI가 통째로 fail한다. 평가 surface가 외부 의존성에 노출된다.
3. **ADR 0003 (answer contract)**: trace_url을 어디에 둘 것인가? `answer.trace_url`이면 schema_version이 깨진다. `diagnostics`로 분리하려면 어차피 추가 surface가 필요하다.

그리고 더 본질적으로 — *두 번째 백엔드*를 추가할 때 또 `run_rag_query`를 편집해야 한다. 결합이 잘못된 자리에 있는 것이다.

## 패턴: pluggable backend registry

대신 [ADR 0013](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0013-observability-as-additive-pluggable-surface.md)은 [`rag_observability.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_observability.py)로 분리하고, 환경변수 `BIDMATE_TRACE_BACKEND`로 게이트한다.

```python
# rag_observability.py
_BACKENDS = {
    "none":     _NoopTraceContext,
    "langfuse": _LangfuseTraceContext,
    "otel":     _OtelTraceContext,
}

def make_trace_context(backend: str | None = None) -> TraceContext:
    backend = backend or os.environ.get("BIDMATE_TRACE_BACKEND", "none")
    factory = _BACKENDS.get(backend, _NoopTraceContext)
    try:
        return factory()
    except ImportError as e:
        return _NoopTraceContext(unavailable_reason=f"missing_dependency:{e.name}")
    except Exception as e:
        return _NoopTraceContext(unavailable_reason=f"backend_init_error:{e}")
```

이 모양은 익숙해야 한다 — [ADR 0006의 LLM judge](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0006-llm-judge-on-real-data-only.md), [ADR 0011의 synthesis](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0011-llm-synthesis-as-additive-ablation.md)도 같은 registry 패턴이다. **judge → synthesis → trace**, 세 곳에 같은 한 가지 추상화가 적용되어 있다. 코드베이스 전체에서 "pluggable backend는 어떻게 추가하는가"의 답이 하나다.

`_StageTimer`는 단지 `trace=` kwarg를 받아서, non-noop이면 자식 span을 연다.

```python
# rag_core.py
class _StageTimer:
    def __init__(self, name, trace=None):
        self.name = name
        self.trace = trace

    def __enter__(self):
        self._t0 = time.perf_counter()
        if self.trace is not None:
            self._span = self.trace.span(name=self.name)
            try:
                self._span.__enter__()
            except Exception as e:
                self._span = None  # fail-closed
        return self
```

`run_rag_query` 본체는 한 줄도 백엔드를 알 필요가 없다. baseline 케이스(`BIDMATE_TRACE_BACKEND=none`)에서는 `_NoopTraceContext.span()`이 `contextlib.nullcontext()`를 반환하므로 stage timer는 동작한다 — 단지 추가 비용이 0일 뿐이다.

## Fail-closed contract — 이 surface의 정의

이 패턴의 *정의적* 속성은 한 줄로 표현된다: **어떤 observability 실패도 query path를 깨지 않는다.**

| 실패 | 행동 |
|---|---|
| Optional dep 누락 | `trace_backend=none`, `trace_unavailable_reason="missing_dependency:langfuse"` |
| Credentials 누락 | `trace_backend=none`, `trace_unavailable_reason="missing_credentials:langfuse"` |
| Backend 생성 실패 | `trace_backend=none`, `trace_unavailable_reason="backend_init_error:..."` |
| `start_trace` 예외 | `trace_url=None`, `trace_error="start_trace:..."`, query 정상 진행 |
| `span()` 예외 (mid-pipeline) | `_StageTimer.__exit__`에서 swallow, 다음 stage span 시도 |
| `finish()` 예외 | `trace_url=None`, `trace_error="finish:..."` |

핵심 invariant: **어떤 실패 모드를 inject해도 결과는 noop run과 byte-identical**(trace_* 키와 timing 변동성을 제거하면). 이 invariant는 [`tests/test_observability_tracing.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/tests/test_observability_tracing.py)의 `test_start_trace_exception_falls_back`로 잠겨 있다.

ADR 0001/0011의 *additive-ablation invariant*가 여기에 그대로 적용된다. baseline 행동은 보존되고, advanced surface는 *옆에* 들어가며, 실패 시 깔끔하게 baseline으로 fall back한다. 같은 한 가지 원칙이 세 ADR을 관통한다.

## Span topology — debugging이 가능한 모양

trace를 attach하는 행위만으로는 안 된다. *어떻게* 분해할지가 디버깅 가치를 결정한다.

| Span name | Cardinality | 핵심 attribute |
|---|---|---|
| `query_analysis` | 2 (pre + post context resolution) | `iteration ∈ {1, 2}` |
| `context_resolution` | 1 | — |
| `retrieve` | N (per retry attempt) | `attempt_index`, `stage`, `top_k` |
| `verify` | N (per retry attempt) | `attempt_index`, `verifier_retry` |
| `answer_generation` | 1 | — |
| `synthesis` | 0 or 1 (LLM 합성 켤 때만) | `prompt_profile` |

retry 루프가 분리된 span이라는 점이 핵심이다. 이슈 #69(verifier retry가 partial-topic grounding을 잘못 인정한 케이스)가 production에서 다시 발생한다고 가정하자. trace에서 `attempt_index=1` retrieve와 `attempt_index=2` retrieve의 doc_id가 다른지, 그리고 그 사이의 verify가 어떤 status로 끝났는지를 *눈으로* 보면 root cause가 즉시 잡힌다. 같은 정보가 `stage_attempts`에 요약돼 있긴 하지만, span sequence는 개별 attempt 단위로 zoom-in이 된다.

## Cadence — 어디서 켜고 어디서 끄는가

| Surface | `BIDMATE_TRACE_BACKEND` | 이유 |
|---|---|---|
| `make smoke` | unset → `none` | 결정적, 외부 의존 0 |
| `pr-eval.yml` (public CI) | unset → `none` | ADR 0005 boundary 보존 |
| Real-data eval | optional `langfuse` | per-case trace는 reviewer 본인 host로 (ADR 0005 aggregate-only commit boundary 그대로) |
| Live demo (Fly.io) | `langfuse` | Streamlit "View trace" 링크 노출, on-call 가능 상태 |

이 4개 surface가 동시에 작동하는 게 fail-closed contract의 효용이다. CI가 trace 없이 결정적으로 돈다는 사실과, production 데모가 동일 코드로 trace 풀어서 본다는 사실이 *같은 코드 경로*에서 보장된다.

## 다른 프로젝트에 적용 가능한 4가지

1. **Observability는 surface다, 모듈이 아니다.** 파이프라인 코드와 trace 코드는 결합 지점이 한 줄이어야 한다 (이 프로젝트에선 `_StageTimer(trace=)` kwarg). 그 한 줄을 통해 vendor를 갈아 끼울 수 있어야 한다.
2. **Default는 noop, 항상.** "trace를 끄지 않으면 켜진다"는 안 된다. CI / smoke / 첫 사용자가 모두 외부 의존성 없이 동작해야 한다. 옵트인 비용은 환경변수 한 줄.
3. **모든 boundary는 fail-closed.** Optional dep 누락 → noop. credentials 누락 → noop. exporter 죽음 → noop. 그리고 *왜 noop이 됐는지*는 `trace_unavailable_reason`에 남긴다 — silently degrade도 안 된다.
4. **같은 registry 패턴을 여러 곳에 재사용한다.** judge / synthesis / trace를 *전부* 같은 `_BACKENDS = {...}` 모양으로 만들면, 새 contributor가 첫 backend를 추가할 때 다른 두 곳을 보고 패턴을 학습한다. 한 코드베이스에 한 가지 "pluggability"의 답.

## 다음 글에서

[외부 baseline 라이브 비교 — LangChain RetrievalQA · LlamaIndex QueryEngine](#) — *대칭 metric subset*만 비교하고 *비대칭 metric*은 `null`로 명시한다는 ADR 0009 메서드론. "왜 자체 구축?" 질문에 정량 답변을 만드는 과정.

---

- 관련 ADR: [0013](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0013-observability-as-additive-pluggable-surface.md), [0011](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0011-llm-synthesis-as-additive-ablation.md), [0006](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0006-llm-judge-on-real-data-only.md), [0001](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0001-preserve-naive-baseline.md)
- 구현: [`rag_observability.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_observability.py), [`rag_core.py:_StageTimer`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_core.py)
- Fail-closed regression test: [`tests/test_observability_tracing.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/tests/test_observability_tracing.py)
- 운영 가이드: [`docs/observability.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/observability.md)
