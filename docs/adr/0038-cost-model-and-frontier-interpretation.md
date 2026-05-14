# 0038: Cost model: PRICING_PER_MTOK_USD lookup table; frontier x-axis = measured $/query

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) (deferral, now superseded),
  [ADR 0015](./0015-cost-telemetry-additive.md) (cost telemetry design),
  [ADR 0009](./0009-external-baseline-comparison.md) (external baseline infra),
  [`rag_synthesis.py`](../../rag_synthesis.py) `PRICING_PER_MTOK_USD` / `compute_cost_usd()`,
  [`eval/run_eval.py`](../../eval/run_eval.py) `evaluate_run()`,
  [`reports/external_baselines.json`](../../reports/external_baselines.json),
  issue #449, issue #177

## Context

ADR 0025 deferred the cost-accuracy frontier (issue #177) until three conditions were
met. This ADR satisfies **conditions 2 and 3** of ADR 0025:

- **Condition 2** (cost model): `rag_synthesis.py` already implements
  `PRICING_PER_MTOK_USD` + `compute_cost_usd()` (ADR 0015). This ADR documents that
  lookup table as the canonical cost model and wires `tokens_in / tokens_out /
  cost_estimate_usd` into `eval_summary.json.case_results[i]` via `evaluate_run()`.
- **Condition 3** (frontier interpretation): This ADR defines the x-axis unit, the
  three reading anchors (#177 spec), and the stub-exclusion rule.

**Condition 1** (real-backend run) is satisfied independently by running
`make external-baselines-langchain` (or `-llamaindex`) with an API key and committing
the resulting `reports/external_baselines.json`. That step is covered in issue #449
and is not a code change.

## Decision

**Use `PRICING_PER_MTOK_USD` in `rag_synthesis.py` as the canonical cost model.**
Per-query cost is computed by `compute_cost_usd(model, tokens_in, tokens_out,
cache_read_tokens, cache_write_tokens)` (longest-prefix model-id match, unknown model
→ `None`, 6-decimal-place rounding). No estimate is fabricated for models not in the
table — `None` propagates through to `case_results[i].cost_estimate_usd` and is
excluded from aggregation.

`evaluate_run()` in `eval/run_eval.py` now extracts four fields from
`prediction["diagnostics"]["synthesis"]` and merges them into each case result:

| field | source |
|---|---|
| `tokens_in` | `synthesis["tokens_in"]` |
| `tokens_out` | `synthesis["tokens_out"]` |
| `cost_estimate_usd` | `synthesis["cost_estimate_usd"]` |
| `llm_model` | `synthesis["model"]` |

All four fields are always present in `case_results[i]` (never absent). For
stub/hashing backends all four are `null`; for real Anthropic API backends they are
populated.

**Frontier interpretation** (issue #177 three reading anchors):

- **x-axis**: `sum(case_results[i].cost_estimate_usd)` for the n evaluated cases,
  in USD. Self-hosted ablations have cost = `null` → treated as x = 0 on the plot
  (labelled "self-hosted" in the legend, not plotted on the cost axis).
- **y-axis**: `accuracy.mean` with bootstrap 95% CI band.
- **Production sweet spot**: lowest-cost external backend whose accuracy CI
  lower bound exceeds the acceptable floor threshold (project-defined, default 0.70).
- **Accuracy ceiling**: best in-repo ablation accuracy (x = 0). Any paid backend
  priced above the ceiling with equal or lower accuracy is dominated.
- **Cheapest acceptable floor**: the external backend with the lowest cost that
  still clears the acceptable floor. Points below the floor are plotted as grey
  non-Pareto dots.

The actual frontier plot (`scripts/plot_pareto.py` extension or a new
`scripts/plot_cost_frontier.py`) is deferred to a follow-up PR under issue #177.
This ADR only locks in the cost model and interpretation schema.

## Consequences

Easier:

- **Every future real-API eval run automatically yields per-case cost.**
  `evaluate_run()` requires no further changes; callers writing `eval_summary.json`
  inherit `tokens_in/out/cost/llm_model` in `case_results` at no extra cost.
- **ADR 0025 can be closed.** All three re-open conditions are now satisfied once
  the external baseline real run is committed (issue #449).
- **The "no fabricated numbers" posture is preserved.** Cost is only populated when
  the SDK `usage` object is present; unknown models remain `null`.

Costs / constraints:

- `case_results[i]` now has four additional keys. Any downstream consumer that
  iterates known keys (e.g., a tight schema validator) must allow extras. Existing
  consumers (`summarize_run`, `metric_block`, leaderboard renderer) use `.get()`
  access and are unaffected.
- The frontier plot remains unbuilt until issue #177 resumes. This ADR does not
  produce the image — it only guarantees the data pipeline is in place.
- `PRICING_PER_MTOK_USD` uses 2026-Q2 public list prices. If Anthropic reprices,
  the constant must be updated in `rag_synthesis.py`. No auto-update mechanism is
  planned.

## Alternatives considered

- **Aggregate cost at the ablation level only (not per-case).** Simpler, avoids
  the `evaluate_run()` change. *Rejected:* per-case cost enables per-query-type
  breakdowns (metadata vs. multi-doc vs. comparison queries) and is consistent with
  the existing per-case latency field. The incremental code is 4 lines.
- **Defer wiring until the plot script is written.** *Rejected:* decouples data
  availability from plotting. Wiring first means the data appears in every eval run
  going forward, including historical replays, without needing a re-run.
- **Use a separate cost model file (YAML/JSON).** *Rejected:* `PRICING_PER_MTOK_USD`
  in `rag_synthesis.py` is already the single source of truth used by
  `compute_cost_usd()` and tested in `tests/test_synthesis_cost_telemetry.py`.
  Duplicating it to a config file introduces drift risk.
