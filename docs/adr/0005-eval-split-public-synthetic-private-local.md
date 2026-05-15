# 0005: Eval split — public synthetic vs private local

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`eval/config.yaml`](../../eval/config.yaml), [`eval/real_config.example.yaml`](../../eval/real_config.example.yaml), [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md), [`docs/real-data/private-hardcase-benchmark.md`](../real-data/private-hardcase-benchmark.md), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md)

## Context

The system has two evaluation needs that pull in opposite directions:

- **Public reproducibility.** Anyone cloning the repo must be able to
  run a meaningful eval without secrets, paid APIs, or data we cannot
  redistribute. README metrics must be backed by a public artifact.
- **Honest signal.** Synthetic RFPs do not exercise the failure modes
  that show up on real procurement documents — ambiguous metadata,
  scanned PDFs, off-distribution phrasing. Real-data eval is where the
  failure taxonomy actually comes from.

A single eval set cannot do both jobs. Anything we publish gets
optimized against, and anything we cannot publish cannot anchor
public claims.

## Decision

Maintain two eval surfaces side-by-side:

- **Public synthetic** (`eval/config.yaml`, `data/raw/`). Committed,
  CI-runnable on every PR (`make eval`, the eval delta workflow),
  drives README metrics. Source of truth for *"is the system still
  shipping the contract it claims?"*. Uses the hashing embedding
  backend so it runs offline.
- **Private local** (`eval/real_config.example.yaml` as the
  scaffold; the actual config and corpus stay out of git). Run
  locally on real procurement documents. Source of truth for *"what
  failure modes are real?"*. Outputs (`reports/real100/`) and inputs
  (`data/files/`, `data/data_list.csv`, the local config) are
  `.gitignore`d.

The boundary is enforced by the example-file convention
(`*.example.yaml`) and by `.gitignore`. Any new eval surface picks a
side: public-redistributable, or strictly local.

## Consequences

**Wins**

- The CI eval delta job (`.github/workflows/pr-eval.yml`) can be
  honest about what it does and does not cover — it measures the
  public synthetic surface only.
- Failure taxonomies and prioritized backlog items can be grounded
  in real-data observations without leaking the documents.
- Confidentiality is not a per-file judgment call; the example /
  gitignore split is the convention.

**Costs**

- Two configs to keep in shape. When the schema of a case evolves
  (new required field, new metric key), both must update or the
  private surface silently drifts.
- README metrics under-report the failure rate that real-data work
  actually sees. Aggregate-delta reports
  (`docs/real-data/private-100-doc-experiments.md`) are needed to bridge that
  honestly.
- Reviewers cannot reproduce private-surface numbers. They must trust
  the aggregate / delta reports plus the public-surface
  reproducibility.

## LLM-judge gate layers (ADR 0006 / 0012 / 0014, consolidated)

Three successive ADRs layered LLM-judge surfaces onto the two eval splits. Those ADRs are Superseded here; their decisions remain in force.

**Gate 1 — real-data only (ADR 0006, accepted)**  
LLM-judge permitted on `eval/real_config.local.yaml` runs only. Output: per-case `judge.local.json` (gitignored) + aggregate `judge.agreement_with_verifier` (committable). Backend: `BIDMATE_JUDGE_BACKEND` — `stub` | `openai_compatible`. The deterministic verifier remains the gate; the judge is a second opinion.

**Gate 2 — public synthetic stub-default (ADR 0012, accepted)**  
LLM-judge permitted on `eval/config.yaml` provided CI runs stub-only (`BIDMATE_SYNTHETIC_JUDGE_BACKEND=stub`, deterministic, network-free). Live backend is offline opt-in via `make synthetic-judge`. Committable aggregate: `reports/synthetic_judge.aggregate.json` (ADR 0005 allowlist). Adds `faithfulness`, `answer_relevance`, `agreement_with_verifier`.

**Gate 3 — RAGAS-style enrichment (ADR 0014, accepted)**  
Four-metric RAGAS-style judge (`faithfulness`, `answer_relevance`, `context_precision`, `context_recall`) as additive enrichment on the synthetic surface. Cache by content hash (`reports/judge_cache/`, gitignored). Hard token-budget cap via `BIDMATE_JUDGE_TOKEN_BUDGET`. Per-case verdicts stay local; aggregate at `eval_summary.json:judge_ragas` is committable.

**Shared invariants (unchanged):** ADR 0004 reproducibility (CI never calls live LLM); ADR 0003 answer contract (judge never affects `answer.status`); ADR 0005 commit boundary (per-case text stays local).

## Alternatives considered

- **Public-only.** Rejected: synthetic data hides the failure modes
  that matter; we would be optimizing for the wrong thing.
- **Private-only.** Rejected: nothing reproducible to publish; no
  reviewer can validate any claim.
- **One config with a private-cases extension loaded conditionally.**
  Considered. Rejected because the two surfaces have different
  purposes (PR gating vs. real-data taxonomy), and conflating them
  makes both harder to defend in review.
