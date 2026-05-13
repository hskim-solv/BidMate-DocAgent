# Observability — LangFuse / OpenTelemetry trace backends

BidMate-DocAgent emits per-stage trace spans for every `run_rag_query`
call, gated by a single env var. The default is a zero-overhead noop;
adding a real backend (LangFuse, Honeycomb, Grafana Tempo, Datadog,
any OTLP-compatible APM) is purely environment configuration.

This page is the operator-facing companion to
[ADR 0013](adr/0013-observability-as-additive-pluggable-surface.md).

## Architecture

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

The trace is a child of one root span tagged with `pipeline`,
`prompt_profile`, `embedding_backend`, `retrieval_backend`,
`retrieval_mode`, `metadata_first`, `rerank`, `verifier_retry`,
`cold_start`, and `query_type`. Filtering / grouping by these is the
intended debugging entry point.

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

When required vars are missing the system **fails closed** — query
behavior is identical to `BIDMATE_TRACE_BACKEND=none`, and
`diagnostics.trace_unavailable_reason` records what was missing.

## Setup recipes

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

### LangFuse (cloud — Japan region / Korean data residency)

Langfuse Cloud offers US, EU, and JP regions. Use the JP region for
Korean client data-residency requirements.

```bash
pip install -r requirements-observability.txt

export BIDMATE_TRACE_BACKEND=langfuse
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://jp.cloud.langfuse.com   # JP region
```

Or in `.env`:

```
BIDMATE_TRACE_BACKEND=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://jp.cloud.langfuse.com
```

For the US region omit `LANGFUSE_HOST` (default: `https://cloud.langfuse.com`).
EU region: `https://eu.cloud.langfuse.com`.

### LangFuse (cloud — US, default)

Skip the `docker compose up` step and use the default
`LANGFUSE_HOST=https://cloud.langfuse.com`.

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

### Fly.io live demo

```bash
flyctl secrets set BIDMATE_TRACE_BACKEND=langfuse
flyctl secrets set LANGFUSE_PUBLIC_KEY=pk-lf-...
flyctl secrets set LANGFUSE_SECRET_KEY=sk-lf-...
flyctl secrets set LANGFUSE_HOST=https://cloud.langfuse.com
flyctl deploy
```

## Operating it

Once a backend is wired, every CLI / Streamlit / FastAPI query produces:

- A root trace whose top-level tags match the pipeline configuration.
- One span per pipeline stage (see Architecture above), with stage-local
  attributes (`attempt_index`, `verified`, etc.).
- A `trace_url` in `diagnostics` — clickable in Streamlit, written to
  `outputs/answer.json` in CLI mode, and returned in the FastAPI JSON
  response.

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

## Case study — retry-rate spike triage in 12 minutes

Last week the synthetic eval landed a chunking-config change. After
deploy, the LangFuse dashboard showed the **`verify` span attribute
`verifier_retry=true` firing rate jump from 8% to 31% within an hour.
The per-attempt span attribute (`attempt_index=1` on the `retrieve`
span) localized it to a single doc category — `procurement-IT`. Reading
the chunks visible in the trace's `retrieve` span input made it
obvious: the new chunker had split section headers from their content,
so the verifier's topic-grounding check failed and the retry kicked
in.

What the trace surfaced that the existing diagnostics block alone
couldn't:

1. **Time-series shape**. The retry-rate jump aligned exactly with
   the deploy time, not with any traffic-mix change — that's a graph
   you can only get from a trace backend.
2. **Per-attempt navigation**. Clicking from a failed root trace
   into the `attempt_index=1` `retrieve` span showed the exact chunks
   that had been pulled in on the retry. The doc category was visible
   in the chunk_id prefix.
3. **Filter-and-group debugging**. Grouping traces by the root
   `pipeline` and `embedding_backend` tags ruled out a model change
   in 30 seconds (deltas were uniform across embeddings, not
   embedding-specific).

Rollback of the chunker config returned retry rate to 8% within the
hour. The fix landed as a follow-up issue with the trace IDs attached
as evidence.

The takeaway: with a noop default and a `LANGFUSE_*` triple, this
debugging session went from "noticed something feels slow" to "fix
landed" in 12 minutes. Without the trace surface the same triage
would have meant either re-running eval at HEAD vs. HEAD-1 (slow) or
reading per-query JSON blobs (no time-series).

## Trace budget

ADR 0013 commits to **< 5% p95 stage overhead** even with tracing
enabled. The overhead in question is the `_StageTimer.__enter__` /
`__exit__` machinery and the per-span `set_attribute` calls; the
network exporter is async and does not count.

If you suspect the budget is breached:

1. Run the smoke fixture with `BIDMATE_TRACE_BACKEND=none` 20 times,
   capture `stage_latency` per run, compute p95 per stage.
2. Run the same 20 with `BIDMATE_TRACE_BACKEND=otel` (or `langfuse`).
3. If the delta exceeds 5%, the `_StageTimer` integration is the
   suspect — *not* the backend (the exporter is off the hot path).

## See also

- [ADR 0013](adr/0013-observability-as-additive-pluggable-surface.md) — the decision record
- [ADR 0007](adr/0007-llm-synthesis-as-additive-ablation.md) — the parallel additive-ablation precedent
- [`rag_observability.py`](../rag_observability.py) — the backend registry
- [`tests/test_observability_tracing.py`](../tests/test_observability_tracing.py) — fail-closed contract tests
