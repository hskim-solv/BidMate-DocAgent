# 0041: Agent budget cap contract

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0040](./0040-react-agent-loop-additive-preset.md) (ReAct preset),
  [ADR 0003](./0003-structured-answer-citation-contract.md) (answer contract),
  [ADR 0015](./0015-cost-model-telemetry.md) (cost telemetry),
  issue #673

## Context

The `react_loop` node introduced in ADR 0040 iterates until evidence
is grounded or the planner calls `abstain`.  Without an explicit cap,
a pathological query could trigger unbounded LLM calls, causing latency
spikes, runaway API cost, and non-deterministic CI behavior.

Three independent budget axes need explicit contracts:
- **Iteration count** — LLM planning turns per query.
- **Latency** — wall-clock time the loop may consume.
- **Tokens** — not enforced by the loop but exposed in telemetry for
  cost attribution (ADR 0015).

## Decision

The `react_loop` node enforces a **two-axis hard cap** and a
**one-axis soft telemetry** contract:

### Hard caps (enforced by `react_loop`)

| Parameter | Env var | Default | Enforcement |
|---|---|---|---|
| `max_iterations` | `BIDMATE_PLANNER_MAX_ITERATIONS` | 5 | Loop exits after N calls to `plan_next` |
| `max_latency_ms` | `BIDMATE_PLANNER_MAX_LATENCY_MS` | 8000 | Checked at start of each iteration; exits if elapsed ≥ cap |

When either cap is reached:
- The loop sets `ctx.evidence` to whatever was retrieved in the last
  successful `retrieve_evidence` call (may be empty).
- `_phase_build_answer` emits `status: insufficient` + `reason: agent_budget_exceeded`
  if `ctx.evidence` is empty, consistent with ADR 0003 abstention.
- `stage_attempts` records the cap-exit event for telemetry.

### Soft telemetry (not enforced)

`input_tokens` / `output_tokens` are recorded in each `planner_meta`
dict inside `stage_attempts`.  ADR 0015 cost telemetry aggregates these
per-query.  A per-query token cap is deferred until cost telemetry
confirms the distribution on real queries.

### Budget dict passed to `Planner.plan_next`

```python
budget = {
    "iterations_left": max_iterations - iteration,  # int
    "ms_left": max(0.0, max_latency_ms - elapsed_ms),  # float
}
```

`LLMPlanner` surfaces this in the user prompt so the LLM can self-
regulate (prefer `abstain` when `iterations_left == 1`).

### Non-determinism tolerance

When `BIDMATE_PLANNER_BACKEND=anthropic` and `temperature=0.0`:
- Real-eval n=100 score variance ≤ ±2 percentage points is the
  acceptance criterion for `agent_react` (vs. `agentic_full` baseline).
- Variance above ±2pp triggers a forced `temperature=0.0` check and
  seed-pinning investigation before the preset is promoted to
  function-level default.

## Consequences

### Positive

- Budget cap guarantees bounded latency (p95 ≤ `max_latency_ms` + one
  planning turn overhead) and bounded cost per query.
- Caps are env-var configurable — operators can tune for their latency /
  cost target without code changes.
- `BIDMATE_PLANNER_BACKEND=static` (default) makes `max_iterations`
  effectively a retrieval retry count, not an LLM call count — CI is
  always LLM-free.

### Negative / Trade-offs

- Hard cap means the loop may exit before full grounding. Accepted:
  ADR 0003 abstention (`status: insufficient`) is a valid first-class
  answer, not an error.
- Different operators may want different defaults — deferred to a
  per-tenant config surface as a follow-up.

## Rollback

Remove `agent_react` from `eval/config.yaml` and `PIPELINE_PRESETS`.
`react_loop` is never reached for other presets; cap enforcement code
is contained in `rag_graph_react._react_loop_node`.
