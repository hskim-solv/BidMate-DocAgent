# 0012: RAGAS-style LLM-judge as additive enrichment on the synthetic surface

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: refines [ADR 0006](./0006-llm-judge-on-real-data-only.md); preserves [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0003](./0003-structured-answer-citation-contract.md), [ADR 0004](./0004-verifier-retry-policy.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md); reuses backend pattern from [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md)
- **Deciders**: hskim

## Context

[ADR 0006](./0006-llm-judge-on-real-data-only.md) restricted LLM-as-judge to the real-data eval surface for three valid reasons: external dependency, per-query token cost, and harder reproducibility on the public CI path. The decision held — and still holds — for *gating* metrics. But it left a gap visible to senior reviewers:

> "The public-synthetic accuracy=0.906 number is retrieval-grounded but not LLM-graded. A reviewer's first instinct is *judged by what?*"

The deterministic verifier answers that for **grounding rigor** (claims-citation alignment, evidence coverage, format compliance), but not for the multi-dimensional quality questions a RAGAS-style read surfaces:

1. **Faithfulness** — do answer claims actually appear in the cited evidence?
2. **Answer relevance** — does the answer address the query, or does it drift?
3. **Context precision** — what fraction of the retrieved evidence is on-topic?
4. **Context recall** — does the evidence cover what the answer needs?

These are *enrichment* signals, not gates. A senior review wants to see them alongside the deterministic numbers; they do not replace anything.

The same engineering shape that worked for [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (LLM synthesis as additive ablation, never replacing the extractive baseline) applies here: **add the RAGAS judge alongside the existing surface, never replace any existing metric, keep the CI deterministic and free by default.**

## Decision

A RAGAS-style LLM-judge is permitted as an **opt-in additive enrichment** on the **public synthetic eval surface**:

- **Default off.** `BIDMATE_JUDGE_BACKEND=stub` is the CI default. Stub is deterministic, network-free, zero-cost, and the public CI workflows (`pr-eval.yml`) do not invoke the judge at all. ADR 0004's reproducibility argument holds.
- **Opt-in paid mode.** `BIDMATE_JUDGE_BACKEND=openai_compatible` (or `anthropic`) calls the configured model with a per-case prompt that asks for all four RAGAS scores in a single JSON response. Invoked manually via `make smoke-with-judge` or `python3 eval/llm_judge.py`. Never invoked by automated CI.
- **Cache by content hash.** Each `(query, summary, evidence[:3])` SHA256 hash maps to a cache file under `reports/judge_cache/` (gitignored). A re-run with unchanged inputs has zero token cost. Cache invalidation is by re-hashing; the existing input/output discipline is enough.
- **Token budget cap.** `BIDMATE_JUDGE_TOKEN_BUDGET` (default 200,000 input-token estimate per full eval run). If reached, the script refuses to continue rather than racking up unbounded cost. Users override the env var deliberately.

### Output schema

Per-case verdict (local-only, gitignored):

```json
{
  "id": "case_id",
  "faithfulness": 0.0–1.0,
  "answer_relevance": 0.0–1.0,
  "context_precision": 0.0–1.0,
  "context_recall": 0.0–1.0,
  "reason_short": "string, ≤ 200 chars"
}
```

Committable aggregate (lives at top-level of `reports/eval_summary.json` under `judge_ragas`):

```json
{
  "faithfulness": float,
  "answer_relevance": float,
  "context_precision": float,
  "context_recall": float,
  "n": int,
  "ci": { "<metric>": { "mean": ..., "ci_lo": ..., "ci_hi": ... } }
}
```

The aggregate is mean ± 95% bootstrap CI per metric, reusing [`eval/bootstrap.py`](../../eval/bootstrap.py). No per-case payload crosses the commit boundary; `scripts/run_real_eval_delta.py:SAFE_TOPLEVEL_KEYS` whitelists `judge_ragas` with explicit sub-key allowlisting.

### Refines ADR 0006, doesn't supersede it

ADR 0006's gate-only restriction stays: the deterministic verifier remains the source of truth for `answer.status` (supported / partial / insufficient). The RAGAS judge contributes *enrichment metrics*, not status decisions. The two surfaces serve different epistemic purposes:

- **ADR 0006 judge** (real-data, status-style): "does the model's read of the evidence agree with the verifier's call?" — `agreement_with_verifier` is the headline.
- **ADR 0014 judge** (synthetic, RAGAS-style): "how does the answer score on four quality dimensions?" — four numeric scores, each with a CI.

They coexist in the same `scripts/llm_judge.py` backend infrastructure (stub / openai_compatible / anthropic) but write to different top-level keys (`judge` for ADR 0006, `judge_ragas` for ADR 0014).

## Consequences

**Wins**

- Public-synthetic numbers gain a second-opinion signal that's *not* trained on the same eval set. Reviewer's "judged by what?" question has a concrete answer.
- Same backend idiom as ADR 0006 — no new auth flow, no new env vars (`BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`, optional `BIDMATE_JUDGE_BASE_URL` already exist).
- Caching means re-runs across PRs against the same case set are free, so opt-in cost is bounded to first-time runs and prompt changes.
- ADR 0001 / 0003 / 0004 / 0005 invariants unchanged.

**Costs**

- Per-run token cost when opt-in mode is used. Bounded by the budget cap (~$3-5 per full eval run with Sonnet 4.6 + prompt cache, per #164 estimate). Budget enforcement is a hard refusal, not a warning.
- One more env var combination for users to know about. Mitigated by stub being the default and `make smoke-with-judge` orchestrating the workflow.
- A judge outage on opt-in runs means RAGAS metrics aren't computed for that PR. The deterministic eval still completes; the `judge_ragas` block is simply absent.

**Constraints (unchanged from prior ADRs)**

- Public CI must not call out to any external LLM. Enforced by convention: `pr-eval.yml` does not invoke the judge, and stub is the default everywhere else.
- Aggregate-only commit boundary stays intact. Per-case judge text under `reports/judge_cache/` is gitignored. Aggregate sub-keys are explicit-allowlist extracted by `scripts/run_real_eval_delta.py`.

## Alternatives considered

- **Use RAGAS directly (the upstream library).** Rejected: adds a paid framework dependency and its own opinion on which model to call. The four metrics are well-defined; a 50-line backend-agnostic implementation gives us the same signal with full control over prompt, caching, and budget enforcement.
- **Compute the four metrics deterministically (token overlap / cosine).** Rejected: that's just a fancier version of the existing groundedness / citation_precision metrics. The point is *another model's read* — the same Goodhart concern (#169) applies if we generate metrics from the same retrieval scaffolding being evaluated.
- **Gate CI on RAGAS thresholds.** Rejected for the same reasons as ADR 0006: reproducibility, cost, and external dependency on the *public* path. Future tightening would need a Judge↔Human agreement floor (#169 / ADR 0013-pending), not a raw RAGAS gate.
- **Merge under existing `judge` top-level key.** Rejected: the schemas differ (status-style vs four-numeric-metrics), and the surfaces differ (real-data vs synthetic). Coexistence via separate top-level keys keeps the privacy boundary easier to audit.
