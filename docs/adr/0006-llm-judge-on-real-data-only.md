# 0006: LLM-judge on the real-data surface only

- **Status**: Superseded
- **Superseded by**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers"
- **Date**: 2026-05-11
- **Related**: refines [ADR 0004](./0004-verifier-retry-policy.md); reinforces [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)
- **Deciders**: hskim

## Context

[ADR 0004](./0004-verifier-retry-policy.md) rejected LLM-as-judge on the
**public** path with three concrete reasons: external dependency, per-
query token cost, and harder reproducibility. It also hedged: *"May be
reconsidered if the deterministic verifier hits a ceiling."*

#69 made the ceiling visible. The deterministic verifier's
`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` knob recovered 4 false-abstain
cases on real-data **and** flipped 2 intended abstentions
(`docs/real-data/private-100-doc-experiments.md` Real-data Decision Log entry).
The Decision Log records the trade-off honestly, but **the threshold
itself is arbitrary** — no amount of synthetic eval tuning will
distinguish a "real partial answer" from a "weak hallucination" if
both pass a fraction-of-topics rule. The signal that would actually
discriminate them is *another model's read of whether the answer is
supported by the evidence*.

That signal is too expensive (tokens) and too non-reproducible to
gate the public CI on. But the **real-data cycle** is already manual,
already aggregate-only, and already lives behind the ADR 0005 commit
boundary. Adding a second-opinion judge there is in-scope; adding it
to public CI is not.

## Decision

LLM-as-judge is permitted on the **local real-data eval surface
only**:

- **Allowed**: `eval/real_config.local.yaml` runs, with judge output
  written under `reports/real100/judge.local.json` (per-case,
  git-ignored) and aggregate / agreement metrics rolled into
  `reports/real100/baseline.aggregate.json` (committable under the
  ADR 0005 allowlist).
- **Not allowed**: `eval/config.yaml` (public synthetic),
  `.github/workflows/pr-eval.yml`, `make smoke`, `make eval`. These
  paths stay deterministic, free, offline, and reproducible per
  ADR 0004.

### Contract

- The judge consumes `(query, answer.summary, evidence[:3].text)` and
  returns a structured JSON object:
  ```json
  {
    "judge_status": "supported" | "partial" | "insufficient",
    "judge_grounded": true | false,
    "judge_reason_short": "string, ≤ 200 chars"
  }
  ```
- The deterministic verifier remains the **gate**. The judge is a
  **second opinion**, never a substitute. Status emitted to callers
  is always the verifier's; the judge only contributes to evaluation
  aggregates.
- Aggregate metrics derived from the judge:
  - `judge.status_distribution` — counts of `supported` / `partial` /
    `insufficient`.
  - `judge.grounded_rate` — fraction of cases where
    `judge_grounded == true`.
  - **`judge.agreement_with_verifier`** — fraction of cases where
    `judge_status == answer.status`. **This is the key new metric.**
    A drop here is an actionable signal: the verifier and the judge
    disagree, go look at the case.
- Per-case judge text (the `judge_reason_short` field, raw prompts,
  raw model responses) **stay local**. Only the three aggregates
  above cross the commit boundary.

### Cadence

Manual, like the rest of the real-data cycle. The user invokes
`make real-eval-with-judge` after a retrieval / verifier change and
attaches the resulting aggregate delta to the PR alongside the
deterministic-verifier delta from ADR 0005's flow.

### Backend pluggability

`scripts/llm_judge.py` is backend-agnostic via
`BIDMATE_JUDGE_BACKEND`:

- `stub` (default) — deterministic fixture, no network. Used by
  tests; lets the plumbing be exercised without API keys.
- `openai_compatible` — generic OpenAI-compatible API endpoint
  (works for Anthropic-Compatible mode, OpenAI, vLLM, llama.cpp
  server, etc.). Requires `BIDMATE_JUDGE_API_KEY`,
  `BIDMATE_JUDGE_MODEL`, optional `BIDMATE_JUDGE_BASE_URL`.
- Future backends can be added without touching the upstream
  pipeline.

## Consequences

**Wins**

- Independent signal on real-data quality, gated against
  deterministic verifier output via `agreement_with_verifier`.
- ADR 0005 commit boundary stays intact: judge per-case text is
  never committed.
- ADR 0004 stays intact for the public path: synthetic CI is still
  deterministic, free, offline, reproducible.
- Future threshold tuning (e.g. #89) gains a second-opinion check
  that's harder to overfit than the synthetic eval set.

**Costs**

- Token spend per real-data run (currently ~21 cases × judge calls).
  Bounded by manual cadence and small N.
- An external dependency exists on the real-data surface. A judge
  outage doesn't break the deterministic eval; `agreement_with_verifier`
  simply isn't computed for that run.
- One more thing for the user to remember. Mitigated by
  `make real-eval-with-judge` orchestrating the steps.

**Constraints (unchanged from ADR 0004 + ADR 0005)**

- Public CI must not call out to any external LLM. Enforced by
  convention; no public-surface script imports `scripts/llm_judge.py`.
- Aggregate-only commit boundary is enforced by reuse of
  `extract_aggregate` and its `_assert_no_forbidden` recursive guard.

## Alternatives considered

- **Skip the judge entirely; just tune the deterministic threshold
  more carefully.** Rejected: the threshold is arbitrary by
  construction. Without an independent signal we cannot tell whether
  a tightening pushed false-positives down or just shifted them into
  a different failure mode.
- **Put the judge in public CI behind a feature flag.** Rejected:
  ADR 0004's reproducibility argument still holds for the public
  path. Per-PR token spend on synthetic cases is also unjustified
  — those cases are crisply discriminable without a model in the
  loop.
- **Train a deterministic judge from the LLM-judge labels.**
  Premature; revisit if `agreement_with_verifier` drops below a
  threshold that suggests systematic verifier drift.
