# Production readiness

One-pager for "is this operable?" — health checks, observability, cost,
regression gates, reproducibility. Pulls together what already lives in
[ADR 0008](../adr/0008-evidence-boundary.md) /
[ADR 0013](../adr/0013-observability-as-additive-pluggable-surface.md) /
[ADR 0015](../adr/0015-cost-telemetry-additive.md) and the eval pipeline.

Not a runbook — the runbook is [`docs/operations/deployment.md`](./deployment.md).
Not an architecture tour — those are the ADRs. This is the **operability
surface area** a reviewer or on-call engineer needs in one screen.

## Surface map

| Concern | Where | Default | Failure mode |
|---|---|---|---|
| Readiness probe | `GET /health` ([`api/main.py:114`](../api/main.py)) | 200 once index loaded; 503 otherwise | 503 body has `index_dir`, `load_error`, hint |
| Graceful shutdown | FastAPI lifespan ([`api/main.py:59`](../api/main.py)) | uvicorn handles SIGTERM; index is read-only | No persistent writes to flush |
| Container healthcheck | [`Dockerfile`](../Dockerfile) `HEALTHCHECK` | polls `/health` every 30s, 3 retries | Container restart on 3 consecutive failures |
| Per-stage traces | `BIDMATE_TRACE_BACKEND={none,langfuse,otel}` | `none` (zero overhead) | Fail-closed; reason in `diagnostics.trace_unavailable_reason` |
| Structured logs | `BIDMATE_LOG_FORMAT=json` ([`bidmate_logging.py`](../bidmate_logging.py)) | `text` (human) | `query_start` / `query_complete` events emit `query_hash` only — no PII |
| Cost telemetry | `diagnostics.synthesis.cost_estimate_usd` (ADR 0015) | `stub` backend → 0 | Unknown model → `None`; not a billing replacement |
| Latency SLO | `eval/config.yaml::latency_budgets` + `make check-latency` | per-ablation `p95_ms` ceiling | CI fails on overshoot; orphan budget = warn, not fail |
| Quality regression | [`pr-eval.yml`](../.github/workflows/pr-eval.yml) regression gate | 5% drop on gated metrics → fail | `[ALLOW_REGRESSION: <reason>]` in PR body overrides |
| Reproducibility | `bash scripts/reproduce_eval.sh` | SHA-256 over env-invariant `eval_summary.json` | `BASELINE=<sha>` → exit 2 on mismatch |
| Prompt-injection defense | ADR 0008 evidence boundary (inlined in `rag_core.py`) | regex-strip before LLM call | Defends ADR 0003 contract + ADR 0006 judge |

## What a reviewer asks

**"How do you know it's healthy?"** `GET /health` returns 200 when the
index is loaded, 503 with a structured body otherwise. Eager-load in the
FastAPI lifespan means the first request doesn't pay cold start. The
Docker `HEALTHCHECK` polls the same endpoint every 30s; Fly.io / HF
Spaces probes plug into the same surface.

**"What does observability look like?"** Pluggable, fail-closed, one env
var: `BIDMATE_TRACE_BACKEND=none|langfuse|otel`. Default `none` is what
CI runs — byte-identical pipeline behavior. Per-stage spans
(`retrieve`/`verify` per retry attempt, `synthesis`) with root tags
(`pipeline`, `prompt_profile`, `embedding_backend`, `retrieval_mode`) —
the columns a reviewer actually filters by. Decision: ADR 0013. Setup
recipes (LangFuse self-hosted/cloud, OTel → Honeycomb/Tempo):
[`docs/operations/observability.md`](./observability.md).

**"How do you track cost?"** `diagnostics.synthesis.cost_estimate_usd`
per query, populated from `compute_cost_usd()` (the single price-table
reader). Anthropic prompt caching is on by default — `cache_control:
ephemeral` on system + tool definitions; `cache_read_input_tokens > 0`
on the second call proves it (locked by
`tests/test_synthesis_cost_telemetry.py`). Explicitly **not** the
Anthropic console — order-of-magnitude regression signal, not source of
truth.

**"What stops a bad PR from shipping?"** Three gates run in CI:

1. **Latency SLO** ([`check_latency_slo.py`](../scripts/check_latency_slo.py))
   — observed p95 vs declared `eval/config.yaml::latency_budgets`. No
   per-PR override; declare a new budget or accept the fail.
2. **Quality regression** ([`pr-eval.yml`](../.github/workflows/pr-eval.yml))
   — gated metrics (accuracy, citation_precision, citation_recall) drop
   > 5% relative to baseline → CI fails. `[ALLOW_REGRESSION: <reason>]`
   in PR body skips with an acknowledged audit line.
3. **Branch & issue convention**
   ([`branch-and-issue-check.yml`](../.github/workflows/branch-and-issue-check.yml))
   — branch matches `<type>/issue-<N>[-<slug>]` (ADR 0007); PR body has
   `Closes #N`.

**"Same numbers on another machine?"** `bash scripts/reproduce_eval.sh`
hashes the environment-invariant subset of `eval_summary.json`
(latency / wallclock / timestamps stripped). `BASELINE=<sha> bash
scripts/reproduce_eval.sh` exits 2 on mismatch — cross-host parity is a
contract, not a coincidence. Combined with `DEFAULT_SEED=17` and
`config_sha256` provenance, this is what backs "reproducible eval" in
the README claims.

## Environment vars at a glance

| Variable | Default | Note |
|---|---|---|
| `BIDMATE_INDEX_DIR` | `data/index` | Read-only at runtime |
| `BIDMATE_DEFAULT_PIPELINE` | `agentic_full` | API + Streamlit fallback chain |
| `BIDMATE_LOG_FORMAT` / `_LEVEL` / `_STREAM` | `text` / `INFO` / `stderr` | Use `json` in prod |
| `BIDMATE_TRACE_BACKEND` | `none` | + `LANGFUSE_*` / `OTEL_*` when opted in |
| `BIDMATE_SYNTHESIS_BACKEND` | `stub` | `anthropic` activates cost telemetry |
| `EMBEDDING_BACKEND` | `hashing` (smoke) / `minilm` (real eval) | Default locked by ADR 0019 |
| `BIDMATE_INDEX_BACKEND` | `memory` | Only supported value today; `qdrant`/`pgvector` reserved (issue #176) |

## Non-goals

- **Billing reconciliation** — `cost_estimate_usd` is a regression
  signal, not an Anthropic-console replacement (ADR 0015 explicitly).
- **Auth / multi-tenant** — demo surface, not a hosted service.
- **HA / autoscale** — Fly.io single-machine is the documented target.
- **Persistent index** — read-only in-memory; rebuild via
  `scripts/build_index.py` (container does this on first start if
  `data/index` is empty).
