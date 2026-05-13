# 0015: Cost telemetry as additive observability (extends 0011, 0013)

- **Status**: Superseded
- **Superseded by**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) § "Additive opt-in pattern (generalization)"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (LLM synthesis), [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (trace backends), `rag_synthesis.py`, `tests/test_synthesis_cost_telemetry.py`

## Context

The LLM synthesis path (ADR 0011) already captures
`tokens_in` / `tokens_out` in `diagnostics.synthesis`, but the public
synthetic surface defaults to the stub backend so cost is always zero
in CI. On the real-data flow (`BIDMATE_SYNTHESIS_BACKEND=anthropic`),
the operator has no in-repo signal for *what an answer cost* or
*whether prompt caching is actually helping* — both are first-tier
questions in a senior LLM-Ops review.

The trace backend (ADR 0013) ships span data to LangFuse/OTel, but
those backends are optional and downstream of the query. The pipeline
itself should carry a cost estimate so even the noop trace backend
case ("operator runs locally, no LangFuse account") leaves an audit
trail.

A real billing source of truth is the Anthropic console — we are not
trying to replace it. We need an *order-of-magnitude regression
signal* ("this refactor 10x'd token spend") that lives next to the
existing eval metrics.

## Decision

Treat per-query LLM cost the same way ADR 0013 treats traces: it is
*additive*, *pluggable*, and *fail-closed*.

Concretely:

1. `rag_synthesis.SYNTHESIS_SCHEMA_VERSION` is bumped to **2**. The
   `synthesis` meta dict gains three new keys, always present (may be
   `None`):
   - `cache_read_tokens`
   - `cache_write_tokens`
   - `cost_estimate_usd`
2. `rag_synthesis.compute_cost_usd(model, tokens_in, tokens_out,
   cache_read_tokens, cache_write_tokens)` is the single source of
   truth for the per-Mtok price table. Unknown models return `None`
   (we do not invent prices for stub / openai-compatible deployments).
3. The Anthropic backend captures `cache_read_input_tokens` and
   `cache_creation_input_tokens` from the SDK `usage` object. Tool
   definitions get `cache_control: ephemeral` alongside the existing
   system-prompt cache breakpoint, maximizing cache-hit surface on
   repeat queries.
4. The price card lives in `PRICING_PER_MTOK_USD` keyed by base model
   id (longest-prefix match so dated SKUs resolve). Updates ship as
   small PRs with a one-line provenance note in this ADR's history.

The default backend remains `stub` — public CI never pays, never
reports a cost, never depends on a price card.

## Consequences

Easier:

- Real-data review can answer "what's our $/query?" by reading
  `diagnostics.synthesis.cost_estimate_usd` directly. Aggregation in
  `eval/run_eval.py` can be added in a follow-up PR.
- "Prompt caching is enabled" stops being a wish — `cache_read_tokens
  > 0` on the second call proves it. The contract test
  (`test_meta_promotes_payload_cache_tokens`) locks the surface.
- The ADR 0003 answer contract is untouched; cost lives in
  `diagnostics`, which is explicitly a non-contract surface.

Harder / costs:

- `SYNTHESIS_SCHEMA_VERSION` bumped to 2. Any consumer that pinned to
  v1 must update — this is the explicit "no silent drift" guard from
  ADR 0003 applied to the synthesis meta block. We considered it
  cheaper than introducing a parallel v2 dict.
- The price card needs occasional updates when Anthropic publishes a
  new tier. Owner: whoever opens the next ADR-noteworthy synthesis
  change. The constants live in `rag_synthesis.py:PRICING_PER_MTOK_USD`.
- We are not pricing OpenAI-compatible deployments. Local
  vLLM/llama.cpp would be billed as zero, paid deployments would need
  a per-deployment override — out of scope here.

## Alternatives considered

- **Track tokens only, skip USD**: easier to maintain (no price
  card), but the senior signal of "$/query" is exactly what reviewers
  ask for. Tokens alone require the reader to know the rate card.
- **Source cost from Anthropic billing API**: gives ground truth but
  introduces a paid-API dependency and breaks the offline CI promise.
  Out of scope per CLAUDE.md non-goals.
- **Embed cost in `answer` dict**: would violate ADR 0003 (answer is
  the verifiable contract; cost is a side-effect of generation). The
  `diagnostics` surface is the right home.
- **Separate `rag_cost.py` module**: premature abstraction. The cost
  table lives next to the only producer (synthesis) for now; extract
  it when a second producer appears (e.g., a judge backend).
