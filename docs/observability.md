# Observability

Per-query trace export for `rag_core.run_rag_query`. Default is **off**
(no dependency, no overhead) — opt in with `BIDMATE_TRACE_BACKEND`.

See [ADR 0012](./adr/0012-trace-backend.md) for the design rationale.

## Backends

| `BIDMATE_TRACE_BACKEND` | Status | When to use |
|---|---|---|
| `none` | default | smoke / public CI / demo deploys without an observability stack. Zero overhead. |
| `otel` | available | export to any OTel-compatible APM (Honeycomb, Tempo, Jaeger, Datadog, Grafana Cloud, …). |
| `langfuse_self_hosted` | coming in PR-B (#165) | self-hosted LangFuse — purpose-built LLM trace UI; renders a "View trace" link in the Streamlit demo. |

## Env-var reference

| Variable | Default | Used by | Purpose |
|---|---|---|---|
| `BIDMATE_TRACE_BACKEND` | `none` | all | Backend selector. Unknown value → falls back to `none` with a single stderr warning. |
| `BIDMATE_TRACE_OTEL_EXPORTER` | `console` | `otel` | `console` (JSON spans on stdout) or `otlp_http` (HTTP collector). |
| `BIDMATE_TRACE_OTEL_ENDPOINT` | `http://localhost:4318/v1/traces` | `otel` (`otlp_http`) | OTLP/HTTP endpoint of your collector. |
| `BIDMATE_TRACE_OTEL_SERVICE` | `bidmate-docagent` | `otel` | OTel `service.name` resource attribute. |
| `BIDMATE_LANGFUSE_HOST` | _(none)_ | `langfuse_self_hosted` (PR-B) | Base URL of the LangFuse instance, e.g. `http://localhost:3000`. |
| `BIDMATE_LANGFUSE_PUBLIC_KEY` | _(none)_ | `langfuse_self_hosted` (PR-B) | Project public key. |
| `BIDMATE_LANGFUSE_SECRET_KEY` | _(none)_ | `langfuse_self_hosted` (PR-B) | Project secret key. |

## Span tree

One trace per `run_rag_query`. Spans nest like this:

```
run_rag_query                       tags: pipeline, prompt_profile, embedding_backend, …
├── query_analysis (initial)        attrs: query_type
├── context_resolution              attrs: status, source, context_resolution_ms
├── query_analysis (post_context)   attrs: query_type, entities_count, metadata_ambiguous
├── retrieval_attempt[0]            attrs: attempt_index, stage, top_k, verified, verification_reasons
│   ├── retrieve                    attrs: stage, top_k, retrieval_mode, retrieval_backend,
│   │                                       candidate_count, retrieve_ms
│   └── verify                      attrs: verifier_retry, verified, verification_reasons,
│                                          verify_ms
├── (retrieval_attempt[1]…)         when verifier_retry escalates a stage (ADR 0004)
├── answer_generation               attrs: answer_status, query_type, claim_count,
│                                          citation_count, abstained, answer_generation_ms
└── synthesis                       attrs: synthesis_backend, synthesis_model,
                                           tokens_in, tokens_out, fell_back,
                                           fallback_reason, synthesis_ms
                                    only when prompt_profile == "llm_synthesis" and not abstained
```

OTel attribute namespace is `bidmate.<snake_case>` to avoid collisions
with reserved keys (`http.*`, `db.*`). Top-level trace tags carry
pipeline / prompt_profile / embedding_backend / retrieval_backend per
[#165](https://github.com/hskim-solv/BidMate-DocAgent/issues/165).

Clarification exits (`needs_clarification` for context or metadata)
emit a trace with `output.clarification_status="needs_clarification"`
and `output.clarification_kind` ∈ {`context`, `metadata`} so reviewers
debugging "why does the demo always ask for clarification?" see the
signal.

## OpenTelemetry quickstart

### Default: console exporter (no collector required)

```bash
pip install 'opentelemetry-sdk>=1.27,<2.0'
BIDMATE_TRACE_BACKEND=otel \
  python3 app.py --input_dir data/index --output_dir outputs \
    --query "기관 A의 보안 통제 요구사항은?"
# JSON-shaped span lines print to stdout for run_rag_query +
# query_analysis + context_resolution + retrieval_attempt[0] +
# retrieve + verify + answer_generation, with all bidmate.* attrs.
# outputs/answer.json carries diagnostics.trace_id (32-char hex)
# and trace_url=null.
```

### OTLP HTTP exporter to a local Jaeger / Tempo collector

```bash
docker run --rm -p 4318:4318 -p 16686:16686 \
  -e COLLECTOR_OTLP_ENABLED=true jaegertracing/all-in-one:latest

pip install 'opentelemetry-sdk>=1.27,<2.0' \
            'opentelemetry-exporter-otlp-proto-http>=1.27,<2.0'
BIDMATE_TRACE_BACKEND=otel \
BIDMATE_TRACE_OTEL_EXPORTER=otlp_http \
BIDMATE_TRACE_OTEL_ENDPOINT=http://localhost:4318/v1/traces \
  python3 app.py --input_dir data/index --output_dir outputs \
    --query "기관 A의 보안 통제 요구사항은?"
```

Open <http://localhost:16686>, select service `bidmate-docagent`, find
the trace by id (the run printed it to `outputs/answer.json` →
`diagnostics.trace_id`).

### Honeycomb

```bash
BIDMATE_TRACE_BACKEND=otel \
BIDMATE_TRACE_OTEL_EXPORTER=otlp_http \
BIDMATE_TRACE_OTEL_ENDPOINT=https://api.honeycomb.io/v1/traces \
OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=$HONEYCOMB_API_KEY" \
  python3 app.py --query "..."
```

`OTEL_EXPORTER_OTLP_HEADERS` is the standard OTel SDK env var; the
exporter picks it up automatically.

### Datadog Agent / Grafana Cloud

Point `BIDMATE_TRACE_OTEL_ENDPOINT` at the OTLP/HTTP receiver of your
agent (Datadog Agent: `http://localhost:4318/v1/traces` with
`OTEL_EXPORTER_OTLP_HEADERS="dd-api-key=$DD_API_KEY"`). Grafana Cloud:
endpoint and headers from your stack's "OTLP" tab.

## Failure semantics

Tracer methods never raise. Backend errors (constructor failure, span
emission, HTTP timeout, SDK incompatibility) are caught at the public
method boundary and downgraded to a single stderr warning per
process:

```
[bidmate.tracing] OtelTracer.span(retrieve) failed: ConnectionError: ...
```

The query continues with `result["diagnostics"]["trace_id"]` set
(downstream consumers can rely on the key being present) and
`trace_url` falling back to `None`. If `make_tracer()` cannot
construct the requested backend, it returns `NoneTracer` and the run
proceeds. This is the load-bearing property of the surface — see
[ADR 0012](./adr/0012-trace-backend.md) "Fail-closed contract".

## Privacy boundary

Per [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md),
real-data query text and per-case answers must not leave the local
surface. Hosted LangFuse Cloud is **not** a registered backend — only
self-hosted is in scope. OTLP exporters that ship traces to a hosted
APM (Honeycomb, Datadog, Grafana Cloud) are the user's responsibility:
do not export real-data traces to a third party you have not audited.

## Related

- [ADR 0012 — Trace backend as a pluggable, off-by-default observability surface](./adr/0012-trace-backend.md)
- [ADR 0004 — Verifier-driven retry](./adr/0004-verifier-retry-policy.md) — explains the `retrieval_attempt[i+1]` spans
- [ADR 0011 — LLM answer synthesis as additive ablation](./adr/0011-llm-synthesis-as-additive-ablation.md) — defines the `synthesis` span attributes
- [#165 — Phase 2.4 LLM-Ops observability](https://github.com/hskim-solv/BidMate-DocAgent/issues/165)
