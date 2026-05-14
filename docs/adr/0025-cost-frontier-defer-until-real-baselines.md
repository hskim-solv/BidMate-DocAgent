# 0025: Cost-accuracy frontier deferred until external baseline real runs land

- **Status**: superseded by [ADR 0038](./0038-cost-model-and-frontier-interpretation.md)
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0009](./0009-external-baseline-comparison.md) (external baseline infra), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (LLM synthesis backend), [ADR 0015](./0015-cost-telemetry-additive.md) (cost telemetry), [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) (latency-quality frontier from #124), issues #157 (external baseline real backends — closed infra-only) and #177 (this decision)

## Context

Issue #177 proposed a cost-accuracy frontier plot ("the single most
compelling LLM Ops portfolio image"): x-axis = $ per query,
y-axis = accuracy with bootstrap-CI band, dots = ablations, dashed
line = Pareto frontier. Three structural gaps block a meaningful plot
from being produced today:

1. **All in-repo ablations have token cost = 0.** The 14 ablations in
   `reports/eval_summary.json.ablation.runs` all run on the
   self-hosted stack (BGE-M3 / hashing-backend embedding + stub LLM
   on CI, real local models in user-env). [`README.md`](../../README.md)
   §Limitations already states this as the "비용 영점" (cost-floor)
   property. On a $/query x-axis every in-repo ablation collapses
   onto x = 0, reducing the frontier to a 1-D accuracy-only line.
2. **External baseline real measurements are missing.**
   [ADR 0009](./0009-external-baseline-comparison.md) defined the
   side-by-side comparison surface; issue #157 closed the
   infrastructure side (LangChain / LlamaIndex backends wired,
   `make external-baselines-langchain` / `-llamaindex` targets land).
   But `reports/external_baselines.json` still ships as a stub
   (`backend: "stub"`, `model: "stub"`, `accuracy: 1.0`, n = 42) —
   the user-environment run that produces real Sonnet / Haiku /
   OpenAI numbers is a separate manual step that has not been done.
   Without that file populated, the frontier has no cost-bearing dots
   to plot.
3. **Token diagnostics not wired through eval aggregation.**
   [ADR 0015](./0015-cost-telemetry-additive.md) emits per-call
   `tokens_in / tokens_out` on the LLM synthesis path
   ([`rag_synthesis.py`](../../rag_synthesis.py)). Eval-time
   aggregation into `case_results[i].tokens_*` is not yet implemented,
   so even if a non-stub backend were measured, computing $/query for
   the in-repo dots would require modeling rather than reading.

Issue #124 already shipped a latency-vs-citation_precision Pareto
frontier ([`scripts/plot_pareto.py`](../../scripts/plot_pareto.py),
`make pareto`, output at `reports/pareto.md` + optional
`reports/pareto.png`). The shape — Pareto highlight, optional
matplotlib render, 14 ablations dotted — is the artifact #177
imagined; the missing piece is purely the *cost axis*.

## Decision

**Defer #177 until external baseline real-backend measurements land.**
Do not produce a modeled-cost frontier in the interim. The existing
[`plot_pareto.py`](../../scripts/plot_pareto.py) frontier (latency
p95 vs. citation_precision) remains the portfolio asset for
cost-quality reasoning. [`README.md`](../../README.md) §Limitations'
"비용 영점" framing is now backed by this ADR rather than left as a
caveat.

The deferral is registered as an ADR rather than left as an open
issue comment because (a) the analysis above is non-obvious — a
future contributor who reads "#177 is open" might invest a day
building a modeled-cost plot before discovering it adds no signal,
and (b) the project has a measurement-gated decision pattern (ADR
0019 → 0021) that benefits from being applied consistently.

## Re-open conditions

ADR 0025 re-opens (i.e., #177 work resumes and the frontier plot is
built) when **all three** of the following hold:

1. `reports/external_baselines.json` contains at least one entry with
   `backend != "stub"` (e.g., `langchain_openai_sonnet`,
   `llamaindex_anthropic_haiku`, or `langchain_openai_text_embedding_3_large`)
   and `metrics.accuracy.n >= 32`. The infrastructure for this exists
   (#157 closed); only the user-environment run is pending.
2. [`rag_synthesis.py`](../../rag_synthesis.py)'s ADR 0015
   `tokens_in / tokens_out` telemetry is aggregated into
   `eval_summary.json.case_results[i]` *or* the cost model is
   defended as a configurable lookup table (one $/query estimate per
   ablation, sourced from public 2026-Q2 prices) with the trade-off
   documented in the follow-up ADR.
3. A follow-up ADR (numbered 002x or higher) is opened to document
   the chosen cost model and the frontier plot's interpretation
   (production sweet spot / accuracy ceiling / cheapest acceptable
   floor — the three reading anchors from the original #177 spec).

If condition 1 lands but the resulting plot has only one or two
real-backend dots, the follow-up ADR may instead document that the
external-baseline real-run cadence is too thin to support a frontier
and defer further — same pattern as the
ADR 0019 → 0021 deferred-then-closed loop.

## Consequences

Easier:

- **No fabricated frontier ships.** A modeled-cost plot would look
  authoritative but encode public-price assumptions as if they were
  measurements. The honest-portfolio cost is one image fewer; the
  honest-portfolio benefit is that every plot in the repo is backed
  by a number that actually moved through the eval pipeline.
- **[`README.md`](../../README.md) §Limitations' "비용 영점"
  statement is now ADR-backed.** A reviewer who asks "why no cost
  axis in your ablation table?" gets a measurement-gated answer
  rather than a verbal explanation.
- **[`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) stays
  the canonical Pareto artifact** for now. It is already wired into
  `make pareto`, `reports/pareto.md`, and ablation documentation. No
  contributor needs to choose between two competing frontier scripts.
- **The deferral itself is searchable.** The next contributor who
  considers picking up #177 finds this ADR before re-running the
  analysis.

Costs / honesty:

- The portfolio image #177 imagined ("the single most compelling LLM
  Ops portfolio image" — issue body) does not exist in the repo
  today. A reviewer interested in cost-vs-accuracy can be pointed at
  [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) (latency
  as cost proxy) plus the public token-price table in #177's body,
  but the synthesis is left to the reader.
- The re-open conditions are gated on a user-environment measurement
  step (running `make external-baselines-langchain` / `-llamaindex`
  with real API keys against the synthetic eval surface). That step
  is not on any in-repo automation's critical path; it relies on the
  maintainer choosing to spend the API budget.
- Issue #177 closes pending this ADR. Reopening requires either
  satisfying the conditions above or writing a fresh ADR that
  supersedes 0025 with a different framing.

## Alternatives considered

- **Build a modeled-cost frontier now.** Use public 2026-Q2 prices
  (Sonnet 4.6 $3/$15 per 1M, Haiku 4.5 $0.80/$4, BGE-M3 self-hosted
  $0, text-embedding-3-large $0.13/1M) × per-ablation token estimates
  to produce one plot. *Rejected:* the estimates would be reverse-derived
  from prompt sizes rather than measured. Shipping
  estimate-as-measurement contradicts the "no fabricated numbers"
  posture already taken in [ADR 0019](./0019-embedding-default-stays-minilm.md)
  / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md).
- **Latency-only frontier as substitute.** *Rejected:* this is exactly
  what [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py)
  already provides via #124. Re-shipping the same chart with a
  different label would not advance #177's goal.
- **Build the token-aggregation infrastructure first (ADR 0015 →
  eval pipeline wiring), then the frontier.** *Rejected:* scope creep
  — the wiring is at least a multi-PR effort touching the eval
  aggregation path, and is independently useful (cost reporting per
  query). It belongs to its own issue. This ADR documents the
  *deferral* of #177, not the infrastructure work.
- **Leave #177 open with a comment.** *Rejected:* a comment loses the
  ADR cross-reference (this ADR will appear in
  `docs/adr/README.md`'s Index and dependency graph; a GitHub comment
  will not). The measurement-gated pattern from ADR 0019 / 0021 is
  the project's established way of closing this kind of loop.
- **Close #177 as `wontfix`.** *Rejected:* #177's underlying idea is
  sound — it just needs external-baseline real data to land first.
  `wontfix` would obscure that the work resumes naturally once the
  data exists.

## Cross-encoder reranker deferral (ADR 0026, consolidated)

ADR 0026 (accepted, same date) applied this same measurement-gated deferral pattern to the cross-encoder reranker surface. ADR 0026 is Superseded here; key decisions below.

**Decision (ADR 0026):** Keep the `Reranker` Protocol and `CrossEncoderReranker` in `rag_reranker.py`. Keep `BIDMATE_RERANK_BACKEND=stub` (identity) as CI default — `full_reranker ≡ full` by construction. Do not remove the seam despite 0pp synthetic delta; Protocol is the plug point for HyDE-reranker / LLM-as-reranker follow-ups.

**Context:** On the public synthetic surface (n=42), `full` (rerank blend on) and `no_rerank` (rerank off) are byte-identical in accuracy/groundedness/citation_precision/abstention. The `rerank: true` blend has zero measured lift. Real backends (`bge`, `bge_ko`, `cohere`) are unmeasured.

**Re-open conditions** (all three must hold to flip the default):
1. At least one of `bge` / `bge_ko` / `cohere` backends runs to completion on the public synthetic eval (n=42); results appended to `docs/cross-encoder-reranker.md` §Results.
2. That backend shows `full_reranker` lift of ≥ +3pp on `accuracy` OR `citation_precision` with non-overlapping 95% CIs vs `full`.
3. A follow-up ADR documents the latency/cost trade-off and flips `BIDMATE_RERANK_BACKEND` default.

## See also

- [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) — the
  latency-quality Pareto frontier that ships today (closed via #124).
- [`reports/external_baselines.json`](../../reports/external_baselines.json) —
  currently stub; re-open trigger when it gets a real-backend entry.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) —
  the measurement-gated deferral pattern this ADR follows.
