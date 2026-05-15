# 0004: Verifier-driven retry with strict → relaxed staging

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_verifier.py`](../../rag_verifier.py) (`verify_evidence` + partial-topic grounding policy, extracted from `rag_core.py:L1843/L2053` in PR-J1 / issue #465), [`docs/agentic/verifier-rules.md`](../agentic/verifier-rules.md) (strict → relaxed staging expressed as pseudo-prompts; LLM-migration counter-checks), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md), [`docs/eval/grounding-eval-hardening.md`](../eval/grounding-eval-hardening.md)

## Context

Even with metadata-first retrieval (ADR 0002), the top-k chunks for a
query are sometimes only partially on-topic. A pipeline that always
trusts the first retrieval pass produces confident-sounding but
weakly-grounded answers, which is the failure mode this project most
wants to avoid. The opposite extreme — refusing to answer whenever
evidence is imperfect — produces excessive false abstention, which
`docs/real-data/real-data-failure-taxonomy.md` C6 identified as the dominant
remaining failure on real corpora.

There needs to be a structured way to ask *"is this evidence good
enough?"* and to take a second shot when it isn't, without unbounded
loops or unverifiable answers.

## Decision

Answer generation is gated by `verify_evidence`. The retrieval loop
runs in **stages**:

1. **Strict stage.** Full topic / entity / comparison-coverage
   checks. Evidence must satisfy all required signals or the stage
   fails with explicit `verification_reasons` (e.g.
   `topic_not_grounded`, `missing_comparison_entity:*`).
2. **Relaxed stage** (one retry). Retrieval re-runs with widened
   parameters; the verifier accepts evidence that meets a documented,
   weaker bar. The relaxation is recorded in
   `diagnostics.filter_stage_attempts` so every answer carries its
   own evidence-quality trail.
3. **Abstain.** If the relaxed stage still fails, the answer becomes
   `insufficient` (or `partial` for comparison queries that have only
   some targets — see ADR 0003). No third retry.

The knobs:

- `verifier_retry: bool` per pipeline preset. `agentic_full` has it
  on; `naive_baseline` has it off; `no_verifier_retry` is a
  first-class ablation.
- The strict / relaxed thresholds live in `verify_evidence` and
  related helpers in `rag_core.py`. Changes that move these
  thresholds must update the eval delta and call out the trade-off
  in the PR.

## Consequences

**Wins**

- Abstention is auditable: every abstained answer carries the
  `verification_reasons` that led there, which is what makes the
  taxonomy-driven backlog (#69, #70, #72) actionable.
- Retry cost is bounded (one extra retrieval at most), so the
  latency / cost story stays simple.
- Each component is independently ablatable
  (`metadata_first`, `rerank`, `verifier_retry`), and the eval
  config exposes each as a named run.

**Costs**

- The strict vs relaxed thresholds are policy decisions, not derived
  from first principles. Issue #69 exists precisely because the
  default policy errs strict and produces false abstentions on real
  data.
- Every new failure mode tends to want its own verification reason
  string. The list in `eval/run_eval.py`'s `retry_reason_counts` is
  the source of truth for what is currently tracked.

## Alternatives considered

- **No verifier; always answer with the top-k.** Rejected: this is
  the `naive_baseline` behavior and is preserved for ablation, not
  as the default. It is unsafe for reviewer-facing claims.
- **Unbounded retries with score-based stopping.** Rejected: latency
  is unbounded, and the failure cases that motivate retry are
  exactly the ones where higher scores do not mean better grounding.
- **LLM-as-judge verifier.** Rejected for the public path: it adds
  an external dependency, costs tokens per query, and makes
  reproducible eval much harder. May be reconsidered if the
  deterministic verifier hits a ceiling.
