# 0030: Leaderboard headline includes `agentic_full` alongside `naive_baseline`

- **Status**: accepted
- **Date**: 2026-05-13
- **Deciders**: maintainer (hskim-solv)
- **Related**: issue #476, PR (forthcoming); reinforces ADR 0001 (preserve naive baseline) and ADR 0024 (agentic_full LLM as API default)

## Context

`reports/leaderboard.md` and `docs/eval/leaderboard.md` chart the time series of headline metrics across commits to `main`. The renderer at `scripts/leaderboard.py:67-98` reads `reports/history/*.aggregate.json` and surfaces a single set of metrics per snapshot.

By construction (`scripts/write_synthetic_history.py:42`), each snapshot carries only the **primary run** — currently `naive_baseline` (per `eval/config.yaml` L4). ADR 0001 intentionally preserves `naive_baseline` as the ablation floor, and its metrics are bit-deterministic on the `hashing` backend. The five most recent main commits (`bb494…a7006`) all rendered identical headline values, which is exactly the property ADR 0001 guarantees.

The side effect: agentic-pipeline changes (HyDE expansion `#396`, LangGraph stage 2 `#458`, security screen `#456`, cross-encoder reranker scaffolding, etc.) all move `agentic_full` but leave `naive_baseline` untouched, so the leaderboard headline appears static even when meaningful work has landed. The `agentic_full` results live inside `eval_summary.json::ablation.runs[]` but never cross the history-snapshot boundary, so the leaderboard cannot see them. This is a *visibility* gap, not a measurement gap.

## Decision

Extend the synthetic leaderboard headline to render **two pipelines** as parallel time series: `naive_baseline` (unchanged, ADR 0001 surface) and `agentic_full` (the `full` ablation run).

Mechanism:

1. `scripts/run_real_eval_delta.SAFE_TOPLEVEL_KEYS` accepts a new top-level key `ablation_full`. The aggregate extractor explicitly whitelists its sub-keys (scalar metrics + bootstrap CI sub-block) and refuses anything case-level — same defense-in-depth pattern as `judge_ragas` (ADR 0012) and `retry_effectiveness` (#120).
2. `scripts/write_synthetic_history.py` pulls the `name == "full"` entry from `eval_summary.json::ablation.runs[]`, runs it through the same whitelist, and writes it under `ablation_full` in the history snapshot.
3. `scripts/leaderboard.py` reads `ablation_full` per snapshot and renders a second table (`## Pipeline: agentic_full`) below the existing `## Pipeline: naive_baseline` table in `reports/leaderboard.md`. The Chart.js page renders both as overlaid line series per metric.

**Forward-only migration.** Existing 21 history snapshots have no `ablation_full` key. The renderer treats absent values as `—` and omits the series segment from the chart. A backfill is a separate concern (deferred to a follow-up issue) and not load-bearing — the leaderboard naturally fills as new daily snapshots accrue.

**Knob.** If a future maintainer wants a different second pipeline (e.g. `agentic_full_finetuned`), the change is one constant in `scripts/write_synthetic_history.py` (the ablation `name` to extract) plus the rendering label in `scripts/leaderboard.py`. The ADR explicitly chooses `full` because it is the primary "production" surface (ADR 0024) and the most-stable ablation across the matrix.

## Consequences

**Wins:**

- Agentic-pipeline merges become visible in the leaderboard headline within one day (cron cadence, ADR 0029-adjacent issue #471).
- The two-pipeline pattern reinforces ADR 0001: the baseline is *intentionally* flat alongside an actively-moving `full` series, which is the intended story rather than an apparent stagnation.
- Portfolio: explicit "stable baseline + moving agentic" framing surfaces both the rigor (#0001) and the progress (#0024) axes simultaneously.

**Costs / locks-in:**

- `SAFE_TOPLEVEL_KEYS` gains one entry. Future schema drift in `ablation_full` requires updating the sub-key whitelist (same maintenance pattern as `judge_ragas`).
- `reports/leaderboard.md` width / row count increases. CI gate `scripts/leaderboard.py --check` continues to pin the rendering as a contract.
- The Chart.js page must accommodate two series per metric. Legend + tooltip update.
- Backfill of pre-#476 snapshots is opt-in; the leaderboard chart will show `agentic_full` as a partial series for ~21 days unless backfilled.

**Locked in:**

- The `ablation_full` key name and its sub-key whitelist become part of the aggregate schema contract. Renaming requires either a deprecation cycle or a separate ADR.
- The pairing of `naive_baseline` + `agentic_full` (specifically — not "any ablation") in the leaderboard headline. Adding a third pipeline (e.g. `agentic_full_finetuned` per ADR 0027) requires an ADR or amendment to this one.

## Alternatives considered

- **Expand the existing single table with extra columns** (`baseline_acc`, `full_acc`, …). Wider table, harder to scan, and the chart-rendering path would still need a parallel series anyway. Rejected for readability.
- **Replace `naive_baseline` as the primary run with `agentic_full`**. Would tear up ADR 0001's deliberate baseline-preservation invariant; baseline regressions would be invisible in the headline. Rejected outright — ADR 0001 is the load-bearing constraint here.
- **Separate `reports/leaderboard_full.md` file + a second Jekyll page**. Doubles the maintenance surface (two CI checks, two pages, two render functions) for a story that wants the two series side-by-side. Rejected for cohesion.
- **Render only the latest `agentic_full` row (single point, not a time series)**. Loses the time-series story that is the whole point of the leaderboard. Rejected.
- **Wait for a separate "decision log" surface to host the agentic story**. Already exists in `docs/real-data/private-100-doc-experiments.md` for the real-data eval; the synthetic leaderboard is the public surface and needs its own equivalent. Rejected.
