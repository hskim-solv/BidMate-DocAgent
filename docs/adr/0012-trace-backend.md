# 0012: Trace backend as a pluggable, off-by-default observability surface

- **Status**: proposed
- **Date**: 2026-05-11
- **Deciders**: hskim
- **Related**: extends [ADR 0006](./0006-llm-judge-on-real-data-only.md) and
  [ADR 0009](./0009-external-baseline-comparison.md) backend-pluggability pattern;
  reinforces [ADR 0004](./0004-verifier-retry-policy.md) (visibility into retry behavior);
  preserves [ADR 0003](./0003-structured-answer-citation-contract.md) (no answer-contract change).
  Implements [#165](https://github.com/hskim-solv/BidMate-DocAgent/issues/165) Phase 2.4.

## Context

Phase 2.4 calls for end-to-end LLM-Ops observability — a way to see the
latency, token cost, and per-stage breakdown of one `run_rag_query`
invocation in a tool that is not the local `diagnostics` JSON. Two
viable surfaces exist: LangFuse (purpose-built for LLM trace UX,
self-hostable) and OpenTelemetry (vendor-neutral, exportable to
Honeycomb / Tempo / Datadog / Grafana).

The pipeline already exposes the right *signals*: every stage flows
through `_StageTimer` (`rag_core.py:2811`); `synthesize_answer` returns
a meta dict carrying backend, model, tokens, and fallback reason
(`rag_synthesis.py:107`); the diagnostics dict at `rag_core.py:3701`
already carries the tags an external observer would want (`pipeline`,
`prompt_profile`, `embedding_backend`, `verifier_retry`,
`synthesis.fell_back`, etc.). What is missing is a *delivery contract*
to a backend.

The constraints are inherited:

1. The default path (smoke, public CI, the demo on Fly.io / HF Spaces)
   must stay deterministic, free, offline, and dependency-light.
   Adding `langfuse` or `opentelemetry-sdk` to `requirements.txt`
   violates that.
2. The answer contract (ADR 0003) and the extractive baseline
   (ADR 0001 / `feedback_extractive_invariant`) must be untouched.
   Tracing is observation-only.
3. The real-data surface (ADR 0005) carries query text we do not
   commit; any backend must not exfiltrate that to a third party we
   have not audited.

## Decision

Introduce a `Tracer` Protocol in a new top-level module
`rag_tracing.py`. `run_rag_query` instantiates one tracer per call
(selected by `BIDMATE_TRACE_BACKEND`) and threads it through five stage
boundaries plus a top-level trace.

### Backends and the `none` default

| Backend value | Default? | Use |
|---|---|---|
| `none` | yes | smoke, public CI, demo deploys without an observability stack. Zero overhead, zero imports. |
| `otel` | no | export to any OTel collector (Honeycomb / Tempo / Datadog / Grafana). `ConsoleSpanExporter` is the safety default; `OTLPSpanExporter` (HTTP) is opt-in via `BIDMATE_TRACE_OTEL_EXPORTER=otlp_http`. |
| `langfuse_self_hosted` | no | self-hosted LangFuse (Docker compose, `BIDMATE_LANGFUSE_HOST`). Renders a "View trace" link in the Streamlit demo. **Registered in PR-B.** |

`none` is the default for the same reason `stub` is the default in
ADR 0006 / ADR 0011: the public CI path must remain dependency-light
and offline. The default is also what runs on `make smoke`, so
`scripts/smoke.sh` does not need to set the env var.

### Why two backends, not one

LangFuse and OTel address different reviewer questions:

- **LangFuse** answers *"can I see this trace in a UI built for LLM
  ops, with one URL per query, today, on infrastructure I control?"*
  The self-hosted Docker compose flow is < 5 minutes; the trace UI
  shows prompt, completion, token cost, fallback reasons inline. The
  Streamlit "View trace" link makes the demo immediately legible to
  reviewers who do not run the CLI.
- **OTel** answers *"can this pipeline be wired into the
  observability stack a customer / reviewer already has?"* OTel is
  the only neutral surface that all the major vendors ingest. A
  reviewer with a Honeycomb account or a Grafana stack does not have
  to install LangFuse to see the same span tree.

The cost of the second backend is one ~80-line backend class sharing
the same protocol; the audience for each is genuinely different.
Same trade-off as ADR 0009's two external-baseline backends.

### Why this does not cross the answer-contract / eval-surface line

The tracer is **observation-only**. No tracer method's return value
is ever read by `run_rag_query` to influence routing, retrieval,
verification, or answer generation. The mutation to `result["diagnostics"]`
is three additive keys (`trace_id`, `trace_url`, `trace_backend`);
existing keys are byte-identical to pre-PR output. ADR 0003 schema is
not touched (no `schema_version` bump). ADR 0001's `naive_baseline`
invariant is preserved by construction. ADR 0011's extractive-answer
invariant (`feedback_extractive_invariant`) is preserved for the same
reason.

### Fail-closed contract

Any backend exception (constructor failure, span emit, HTTP timeout,
SDK incompatibility) is caught at the public method boundary inside
`rag_tracing.py` and downgraded to a single stderr warning per
process. The query continues. This is enforced by
`tests/test_tracing_regression.py` and is the **single most important
property of this surface** — the answer is the product, the trace is
diagnostic.

### Per-attempt nested `retrieve` / `verify` spans

Per attempt, not aggregated. ADR 0004's verifier-retry behavior is
the most debugging-relevant signal in the loop; aggregating it would
defeat the trace's purpose. OTel and LangFuse both render nested
spans natively as a Gantt waterfall, so the UX cost is zero.

### Backend pluggability

Same registry pattern as ADR 0006 (`BIDMATE_JUDGE_BACKEND`),
ADR 0011 (`BIDMATE_SYNTHESIS_BACKEND`), and ADR 0009
(`BIDMATE_EXTERNAL_BACKEND`). Future backends drop into the
`_BACKENDS` registry and the env-var selector. No `run_rag_query`
change required.

### Upgrade paths

A future `BIDMATE_TRACE_BACKEND=langfuse_cloud` would add the same
backend class with a different default host. **It is not added now**:
ADR 0005's commit boundary blocks per-case query text from leaving
the local surface, the same concern that gated the LLM judge in
ADR 0006. Hosted LangFuse is in scope only when (a) the corpus is
public-domain or (b) a separate ADR widens the boundary. Neither
holds today.

## Consequences

**Wins**

- Reviewers and customers can see the trace tree, latency, and token
  spend for any `run_rag_query` invocation in the tool of their
  choice — LangFuse (purpose-built UI) or OTel (their existing
  stack).
- ADR 0004's retry behavior becomes a first-class trace signal
  rather than a buried `diagnostics.filter_stage_attempts` field.
- ADR 0011's `synthesis.fallback_reason` becomes a queryable
  attribute in production tracing dashboards — the exact signal
  needed to debug a synthesis regression.
- The default is unchanged (`none`), so smoke, CI, and dependency
  footprint are untouched.

**Costs**

- One new top-level module (`rag_tracing.py`, ~310 lines) to
  maintain. Mitigated by the protocol's narrowness (4 methods + one
  helper handle) and by stable target SDKs.
- ~75 lines of instrumentation woven into `rag_core.run_rag_query`.
  Each is a `with tracer.span(...)` wrapper around an existing
  `_StageTimer` block; the existing timing accumulator is untouched.
- LangFuse SDK is pre-1.0 (semver-major churn). Mitigated by lazy
  import + fail-closed wrapping; an upstream API break degrades the
  feature to `none`, never breaks the answer path.
- Two extra env-var groups for users to learn (`BIDMATE_TRACE_*`,
  `BIDMATE_LANGFUSE_*`). Mitigated by `docs/observability.md`
  centralizing the reference table.

**Constraints (locked in)**

- `result["diagnostics"]["trace_id"]` is always a 32-char UUID hex
  string. Downstream consumers may assume this shape.
- `result["diagnostics"]["trace_url"]` is `str | None`. Streamlit
  uses `None` as the "no link" signal.
- `result["diagnostics"]["trace_backend"]` is the backend name
  (`"none"` / `"otel"` / `"langfuse_self_hosted"`).
- `BIDMATE_TRACE_BACKEND=none` is the default and is what runs on
  `make smoke`, `bash scripts/test.sh`, and `pr-eval.yml`. No
  backend's import is loaded in that path. Verified by
  `tests/test_tracing.py::test_default_backend_is_none`.
- New backends MUST raise no exception out of any `Tracer` method.
  This is the single non-negotiable property of the surface.

## Alternatives considered

- **LangFuse only.** Rejected: a reviewer with a Honeycomb / Datadog
  / Tempo stack should not have to run a second observability tool
  just to see this trace.
- **OTel only, with a LangFuse exporter on top.** Tempting (one less
  protocol to maintain), but LangFuse's OTel exporter does not yet
  carry token-cost / completion-text fields that the native LangFuse
  SDK does, so the demo "View trace" UX would degrade. Revisit when
  parity improves.
- **Bake tracing into `_StageTimer`.** Rejected: `_StageTimer` is
  load-bearing for the local diagnostics dict; coupling it to an
  external SDK violates the existing one-purpose-per-class shape and
  risks the extractive-answer invariant.
- **Make `BIDMATE_TRACE_BACKEND=otel` the default.** Rejected: the
  default would import `opentelemetry-sdk` on every CI job, demo
  deploy, and contributor checkout, even when no one is reading the
  spans. The `none` default mirrors ADR 0006 / 0011 / 0009.
- **Hosted LangFuse Cloud out of the gate.** Rejected: ADR 0005's
  commit boundary blocks per-case query text from leaving the local
  surface. Self-host first.
