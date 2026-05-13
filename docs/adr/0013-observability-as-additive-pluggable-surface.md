# 0013: Observability as an additive, pluggable, fail-closed surface

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: extends [ADR 0001](./0001-preserve-naive-baseline.md); preserves [ADR 0003](./0003-structured-answer-citation-contract.md); reuses backend pattern from [ADR 0006](./0006-llm-judge-on-real-data-only.md) and [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md); respects eval split from [ADR 0005](./0005-eval-split-public-synthetic-private-local.md); same "additive pluggable surface" theme as [ADR 0020](./0020-protocol-based-pluggability.md) (retrieval-side Protocols)
- **Deciders**: hskim

## Context

[`rag_core.py`](../../rag_core.py) already accumulates per-stage timings via the
`_StageTimer` context manager and exposes them as
`diagnostics.stage_latency`. ADR 0011 added `diagnostics.synthesis.{backend, model, tokens_in, tokens_out, latency_ms, fallback_reason}`.
What's missing is the **sink** — a trace viewer where a reviewer (or
on-call engineer) can see per-query stage breakdowns, token counts,
cost trajectories, and failure-mode rates over time.

For an Applied AI / LLM Ops portfolio the trace viewer is the highest-leverage
observability signal: it makes the difference between "this system
returns answers" and "this system is operable in production." The
shape of the integration matters more than the specific vendor —
LangFuse, Honeycomb, Datadog, Grafana Tempo, and any OTLP-compatible
backend should all work without touching the pipeline.

Bundling tracing directly into `run_rag_query` would conflict with
ADR 0001's baseline preservation (the noop default has to stay
deterministic and free) and put the ADR 0005 eval split at risk (a
crash in an exporter could fail CI). The right move is the same shape
as ADR 0011's defense of LLM synthesis: **keep the pipeline behavior
untouched and add observability as an additive, pluggable, fail-closed
surface.**

## Decision

Observability is an *additive* surface exposed through a pluggable
backend registry in [`rag_observability.py`](../../rag_observability.py),
gated by `BIDMATE_TRACE_BACKEND`. Specifically:

- Default `BIDMATE_TRACE_BACKEND=none` runs a noop `TraceContext` whose
  `span()` returns `contextlib.nullcontext()`; the pipeline behavior
  is byte-identical to a build without this module.
- `_StageTimer` in [`rag_core.py`](../../rag_core.py) accepts an
  optional `trace=` kwarg. When non-noop, each timed region also
  opens a child span on the trace.
- A backend registry `_BACKENDS = {"none": ..., "langfuse": ..., "otel": ...}`
  mirrors the [ADR 0011 synthesis registry](../../rag_synthesis.py).
  Adding a new backend means registering a factory; no edits to
  `run_rag_query` are required.
- `run_rag_query` exposes four new diagnostics keys: `trace_url`,
  `trace_backend`, `trace_unavailable_reason`, `trace_error`. None of
  these are part of the ADR 0003 answer contract — they live in
  `diagnostics`, not in `answer`. `schema_version` does **not** bump.

### Span topology

A single `run_rag_query` invocation emits one root trace with these
child spans:

| Span name | Cardinality | Attributes |
|-----------|-------------|------------|
| `query_analysis` | 2 (pre + post context resolution) | `iteration ∈ {1, 2}` |
| `context_resolution` | 1 | — |
| `retrieve` | N (one per retry attempt) | `attempt_index`, `stage`, `top_k` |
| `verify` | N (one per retry attempt) | `attempt_index`, `verifier_retry` |
| `answer_generation` | 1 | — |
| `synthesis` | 0 or 1 (only when `prompt_profile=llm_synthesis`) | `prompt_profile` |

Root-trace tags: `pipeline`, `prompt_profile`, `embedding_backend`,
`retrieval_backend`, `retrieval_mode`, `metadata_first`, `rerank`,
`verifier_retry`, `cold_start`, `query_type`. These are exactly the
columns a reviewer would want to filter or group traces by.

### Backend pluggability

- `none` (default) — `_NoopTraceContext`. Zero overhead. Used by
  `make smoke`, `pr-eval.yml`, public CI, and any reviewer running
  the demo offline.
- `langfuse` — Requires `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`;
  optional `LANGFUSE_HOST` (defaults to `https://cloud.langfuse.com`).
  Imports the `langfuse` package lazily inside the backend factory —
  missing dependency falls back to noop with
  `trace_unavailable_reason=missing_dependency:langfuse`. Trace URLs
  are surfaced via `trace.get_trace_url()` and end up in
  `diagnostics.trace_url`.
- `otel` — Standard OpenTelemetry SDK. Honors `OTEL_EXPORTER_OTLP_ENDPOINT`
  / `OTEL_SERVICE_NAME` per the SDK convention. Optional
  `BIDMATE_TRACE_URL_TEMPLATE` (e.g.
  `https://ui.honeycomb.io/.../trace?trace_id={trace_id}`) renders a
  clickable URL from the otherwise opaque OTLP trace_id.

### Fail-closed contract

The defining property of this surface is that *no observability
failure can break the query path*. Every backend boundary catches
exceptions and falls back to noop:

| Failure | Behavior |
|---------|----------|
| Missing optional dep | `trace_backend=none`, `trace_unavailable_reason="missing_dependency:<pkg>"` |
| Missing credentials | `trace_backend=none`, `trace_unavailable_reason="missing_credentials:<backend>"` |
| Backend constructor raises | `trace_backend=none`, `trace_unavailable_reason="backend_init_error:..."` |
| `start_trace` raises | `trace_backend=<requested>`, `trace_url=None`, `trace_error="start_trace:..."` |
| `span()` raises mid-pipeline | swallowed in `_StageTimer.__exit__`; pipeline continues; subsequent spans still attempted |
| `finish()` raises | `trace_url=None`, `trace_error="finish:..."` |

The **additive-ablation invariant** (from ADR 0001 / ADR 0011 applied
here): with any failure mode injected, the result is byte-identical
(after stripping `trace_*` keys and volatile timings) to a noop run.
This is locked in [`tests/test_observability_tracing.py`](../../tests/test_observability_tracing.py)
as `test_start_trace_exception_falls_back`.

### Cadence

- **Public synthetic CI** (`pr-eval.yml`): `BIDMATE_TRACE_BACKEND` unset
  → noop. No SDK installed. Pipeline behavior unchanged.
- **Real-data eval**: optional. Defaults to noop. A reviewer can opt
  in with `BIDMATE_TRACE_BACKEND=langfuse` for one-off debugging without
  affecting the ADR 0005 commit boundary (aggregate metrics are
  unchanged; only the per-query trace is exported).
- **Live demo**: `BIDMATE_TRACE_BACKEND=langfuse` configured via Fly.io
  secrets. The Streamlit demo surfaces a "View trace" link below
  each answer (per the issue acceptance criteria).

## Consequences

**Wins**

- The system gains a production-grade observability surface — per-stage
  spans, retry-loop visibility, token counts, cost trajectories — without
  putting ADR 0001 (baseline) or ADR 0003 (answer contract) at risk.
- Two vendor-agnostic backends (LangFuse for native UX, OTel for any
  APM) plus a deterministic noop default. Adding Honeycomb, Datadog,
  or Grafana Tempo is environment configuration, not code change.
- Reuses the ADR 0006/0007 backend-registry idiom, so there is now one
  consistent "how to add a pluggable backend" pattern in the codebase
  (judge → synthesis → trace).
- The retry-loop visibility (per-attempt `retrieve` / `verify` spans
  with `attempt_index` attribute) is genuinely useful for debugging
  partial-grounding cases like #69 — historically only summarized
  in `stage_attempts`, now traceable as a span sequence.

**Costs**

- Three optional dependencies (`langfuse`, `opentelemetry-sdk`,
  `opentelemetry-exporter-otlp-proto-http`). All gated behind lazy
  imports inside backend factories. None are required at runtime
  unless `BIDMATE_TRACE_BACKEND` is set to a backend that uses them.
- Small overhead in `_StageTimer.__enter__` / `__exit__` even when
  `trace=None` (one `None`-check per stage). Measured at < 0.1ms per
  query on the smoke fixture; well within the trace-budget constraint
  below.
- One new module + one new env-var family for users to understand.
  Mitigated by the default being `none` (works offline, no setup).

**Constraints (unchanged)**

- ADR 0001: `naive_baseline` runs identically with or without this
  module. `pipeline_cli_choices()` is untouched.
- ADR 0003: `schema_version: 2`, `status` values, `claims[].citations`,
  and `evidence[]` are unchanged. Trace data lives in `diagnostics`,
  not `answer`.
- ADR 0005: real-data per-case traces stay local (LangFuse host of
  the reviewer's choice). Public CI tracing is noop. Aggregate
  metrics are unaffected.
- ADR 0011: `diagnostics.synthesis` keys remain. The new `synthesis`
  span is opened only when LLM synthesis runs.

### Trace budget

Even with tracing enabled, p95 overhead per stage must stay under
**5%** relative to the noop baseline. This bounds the cost of the
span machinery itself (not the network exporter, which is async). If
the budget is breached the `_StageTimer` integration should be
re-examined before any backend is blamed.

## Alternatives considered

- **Bundle tracing directly into `run_rag_query`.** Rejected:
  couples concerns, makes the pipeline harder to read, conflates the
  "what the pipeline does" code with the "how we observe it" code.
  Also makes adding a second backend a `run_rag_query` edit instead
  of a registry edit.
- **Print-only logging.** Rejected: no time-series, no per-stage span
  navigation, no token/cost dashboards. Useful for local debugging
  but does not deliver the LLM Ops portfolio signal the
  [Phase 2.4 plan](../../../../../../.claude/plans/ai-temporal-panda.md)
  is after.
- **Always-on tracing.** Rejected: violates ADR 0005 (public CI must
  be deterministic and free of network dependencies). Also makes the
  smoke test brittle.
- **Wrap-only outer span (one span per query, no children).**
  Rejected: most of the debugging value is in per-stage breakdown —
  knowing that `verify` is the bottleneck or that `retrieve` is
  triggering retries is much more actionable than knowing a query
  took N ms total.
- **One backend instead of two (LangFuse only).** Rejected: LangFuse
  is great for AI-native UX but enterprises often already have
  Honeycomb / Datadog / Grafana Tempo. OTel lets the same instrumentation
  go to any of them at zero code cost.
