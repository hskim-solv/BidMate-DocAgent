# 0040: ReAct agent loop as additive pipeline preset

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline invariant),
  [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (additive opt-in pattern),
  [ADR 0020](./0020-protocol-based-pluggability.md) (4-axis pluggability),
  [ADR 0022](./0022-langgraph-orchestration-stage-1.md) (LangGraph integration),
  [ADR 0023](./0023-hyde-query-expansion-ablation.md) (query expansion pattern),
  [ADR 0024](./0024-agentic-full-llm-as-api-default.md) (3-layer default policy),
  [ADR 0041](./0041-agent-budget-cap-contract.md) (budget cap),
  issue #673

## Context

Phase 1 audit (2026-05-14) found that BidMate-DocAgent is at stage (B)
"agentic RAG" — LangGraph orchestration and bounded verifier retry exist,
but `make_plan` is a deterministic static function and there is no
query-time LLM-driven action selection (ReAct pattern).

The project name "DocAgent" implies autonomous evidence-retrieval agency.
To close the gap between the name and the implementation, and to produce
a senior-engineering portfolio signal (trade-off documentation +
extensible architecture + evaluation discipline), a ReAct agent loop is
introduced as an **additive** fourth pipeline preset.

External reviewer critique (ADR 0024 context) and the senior-positioning
rubric (docs/senior-positioning.md) both flag "when would you upgrade to
a real agent?" as a key signal question — this ADR is the documented
answer.

## Decision

Introduce `agent_react` as the fourth `PIPELINE_PRESETS` entry
(`rag_pipeline_presets.py`), alias `"react"`, and a parallel
`rag_graph_react.py` LangGraph module alongside `rag_graph_agentic_full.py`.

**Three invariants from earlier ADRs are preserved unchanged:**

1. **ADR 0001**: `naive_baseline` golden is bit-identical.
   `_skip_graph=True` and direct-path guard (`pipeline != "naive_baseline"`)
   remain; `agent_react` adds a new branch before the `BIDMATE_ORCHESTRATOR`
   check, not inside it.

2. **ADR 0003**: answer dict contract (`schema_version: 2`) is unchanged.
   `_phase_build_answer` is reused; `react_loop` only populates
   `ctx.evidence` and `ctx.plan` — it does not produce the answer.

3. **ADR 0024 3-layer default policy**:
   - CLI default stays `naive_baseline`.
   - Function default stays `agentic_full`.
   - API surface default stays `agentic_full_llm`.
   `agent_react` is opt-in only (explicit `pipeline="agent_react"` or
   alias `"react"`).

**`Planner` Protocol (ADR 0020 extension):**
`rag_planner.Planner` is the fifth Protocol-based pluggable axis, joining
`VectorStore`, `QueryExpander`, `Reranker`, and the future `Synthesizer`.
`StaticPlanner` delegates to `make_plan` (deterministic default).
`LLMPlanner` activates via `BIDMATE_PLANNER_BACKEND=anthropic`.

**CI contract:**
`BIDMATE_PLANNER_BACKEND=static` (default) keeps every `agent_react`
test deterministic — no Anthropic API calls in CI.

## Consequences

### Positive

- "DocAgent" name is now backed by a genuine ReAct agent loop.
- ADR 0020 4-axis pluggability is extended to 5-axis (Planner).
- The `agent_react` preset produces an independent eval row that can
  be compared against `agentic_full` side-by-side.
- `BIDMATE_PLANNER_BACKEND` env-var pattern is consistent with ADR 0011
  and ADR 0023 opt-in conventions.

### Negative / Trade-offs

- **Non-determinism when `BIDMATE_PLANNER_BACKEND=anthropic`**: LLM
  sampling introduces variance. Mitigated by `temperature=0.0` and
  ADR 0041 budget cap; real-eval n=100 ±2pp tolerance is the acceptance
  criterion.
- **Latency increase**: multi-turn LLM planning adds p95 latency.
  ADR 0041 enforces `max_iterations=5` / `max_latency_ms=8000` caps.
- **Cost**: each planning turn is a billable API call. Mitigated by
  `cache_control: ephemeral` on tool definitions and ADR 0015 cost
  telemetry.
- **Attack surface**: tool_use results could carry injected instructions.
  Mitigated by ADR 0042 evidence-boundary defense (PR-E).

## Alternatives considered

1. **Rewrite `_phase_retrieve_loop` as a ReAct loop**: rejected. Would
   modify a load-bearing path (ADR 0001 risk) and break the JSON-identity
   regression in `tests/test_langgraph_orchestrator_regression.py`.

2. **Use a separate agent framework (CrewAI, AutoGen)**: rejected. Adds
   a new paid/maintained dependency, breaks the LangGraph investment
   (ADR 0022), and is disproportionate for a single-pipeline preset.

3. **Full multi-agent system (planner + retriever + verifier agents)**:
   deferred. Requires multi-document streaming, inter-agent state
   synchronization, and a new eval surface — better scoped as a
   follow-up milestone once `agent_react` proves the single-agent loop.

## Upgrade path

`agent_react` is the "when would you upgrade?" answer.  The upgrade
conditions from `agentic_full`:
- External reviewer confirms p95 latency ≤ budget cap on real eval.
- Cost telemetry shows per-query cost is within operator budget.
- `agent_react` beats `agentic_full` on the LLM-judge recall@20 metric
  by ≥ 2pp on the public synthetic slice (ADR 0012 eval surface).

Until all three conditions are met, `agentic_full` remains the function-
level default (ADR 0024).
