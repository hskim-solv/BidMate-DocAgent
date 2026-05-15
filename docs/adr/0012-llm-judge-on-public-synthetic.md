# 0012: LLM-judge on the public synthetic eval, stub-default

- **Status**: Superseded
- **Superseded by**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers"
- **Date**: 2026-05-11
- **Related**: refines [ADR 0006](./0006-llm-judge-on-real-data-only.md); reuses the backend pattern of [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md); preserves [ADR 0004](./0004-verifier-retry-policy.md) reproducibility
- **Deciders**: hskim

## Context

[ADR 0006](./0006-llm-judge-on-real-data-only.md) introduced an
LLM-judge on the **real-data** eval surface and explicitly rejected
the public-synthetic version with this argument:

> Put the judge in public CI behind a feature flag. **Rejected**:
> ADR 0004's reproducibility argument still holds for the public path.
> Per-PR token spend on synthetic cases is also unjustified — those
> cases are crisply discriminable without a model in the loop.

That reasoning still applies to **live** judge calls in CI. But it
leaves a gap: a portfolio reviewer reading
`docs/eval/ablation-results.md` sees deterministic precision / recall /
nDCG / `groundedness` (bool) and nothing else. There is no public
RAGAS-style signal — no faithfulness, no answer-relevance — because
the only place we run a model judge is the private
`reports/real100/`.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) already
solved a structurally identical problem: it added an LLM-driven
ablation (`agentic_full_llm`) but kept the public CI deterministic by
defaulting to a `stub` backend. The live backend is opt-in via env
var. ADR 0004's reproducibility argument is preserved because CI
never makes a network call.

The same pattern applies here. A **stub-default** judge on the
synthetic surface:

- has zero token cost in CI (the stub mirrors the verifier),
- is fully reproducible (deterministic stub, deterministic
  aggregate),
- exposes a real RAGAS-style signal **on demand** when a developer
  runs `make synthetic-judge` with a live backend.

The scenario ADR 0006 rejected — "live judge in CI" — remains
rejected. The scenario this ADR introduces — "stub judge in CI,
live judge opt-in offline" — is structurally different and does not
violate ADR 0004.

## Decision

LLM-as-judge is permitted on the **public synthetic eval surface**
provided:

- **CI runs the stub backend only.** `pr-eval.yml`, `make smoke`,
  `make eval`, and `bash scripts/test.sh` never invoke a live LLM.
  Stub mode is deterministic, network-free, and produces a
  byte-equal aggregate across runs.
- **Live backends are opt-in offline.** A developer who wants real
  faithfulness / answer-relevance numbers runs
  `make synthetic-judge` after `make eval`, with
  `BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible` plus the
  shared `BIDMATE_JUDGE_*` credentials. The resulting aggregate is
  committed to `reports/synthetic_judge.aggregate.json` (ADR 0005
  aggregate-only boundary). Per-case verdicts stay in
  `reports/synthetic_judge.local.json` (git-ignored).
- **The judge is a second opinion, not a gate.** The deterministic
  verifier's `answer.status` remains the answer-time contract
  (ADR 0003). The synthetic judge contributes only to evaluation
  aggregates; it never affects what `run_rag_query` returns.

### Contract

- The judge consumes per case from `eval_summary.json`:
  `(query, answer.summary, evidence[:3].text, answer_status)`.
- Output per case:
  ```json
  {
    "judge_status": "supported" | "partial" | "insufficient",
    "judge_grounded": true | false,
    "faithfulness": 0.0,
    "answer_relevance": 0.0,
    "judge_reason_short": "≤ 200 chars"
  }
  ```
- Committable aggregate (`reports/synthetic_judge.aggregate.json`):
  - `n`, `faithfulness_mean`, `answer_relevance_mean`,
    `grounded_rate`, **`agreement_with_verifier`**,
    `status_distribution`.
  - Same shape, sliced under `by_query_type`.
- Per-case `judge_reason_short`, raw prompts, raw model responses
  stay local (ADR 0005 commit boundary).

### Backend pluggability

`eval/synthetic_judge.py` mirrors `scripts/llm_judge.py`'s pattern:

- `stub` (default) — deterministic. `agreement_with_verifier == 1.0`
  by construction. Status-derived fixture scores (e.g. supported →
  faithfulness 0.85) keep the aggregate schema populated for
  downstream consumers without claiming any real signal.
- `openai_compatible` — generic OpenAI-compatible endpoint. Reads
  `BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`, optional
  `BIDMATE_JUDGE_BASE_URL` (shared with the real-data judge —
  same model can serve both surfaces).
- Backend choice via `BIDMATE_SYNTHETIC_JUDGE_BACKEND` (independent
  from real-data `BIDMATE_JUDGE_BACKEND`).

### Cadence

Public CI is silent on the live signal — the stub aggregate is
deterministic plumbing only. A developer who wants the real signal
runs `make synthetic-judge` with a live backend manually, attaches
the resulting committed aggregate diff to the PR, and lets reviewers
read the rendered table in `README.md` / `docs/eval/ablation-results.md`.

## Consequences

**Wins**

- Public reviewers see a RAGAS-style faithfulness / answer-relevance
  signal alongside the deterministic metrics, sourced from a
  committed aggregate snapshot.
- ADR 0004 stays intact: CI runs no live LLM, every run is
  reproducible, every run is free.
- ADR 0005 stays intact: per-case judge text never crosses the
  commit boundary.
- ADR 0006 stays intact: the real-data judge is unchanged
  (`scripts/llm_judge.py` not refactored).
- Reuses the backend dispatch pattern from
  [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (stub
  vs. openai_compatible) — one consistent "how to add an LLM"
  idiom across the codebase.

**Costs**

- The committed aggregate goes stale unless re-rendered after each
  retrieval / verifier change. Mitigated by manual cadence — the
  aggregate is a snapshot, not a CI gate, so staleness shows up as
  "this number is from commit X" rather than as a regression.
- Stub-mode aggregate values (faithfulness 0.85 on supported, etc.)
  are *not* a real signal. The README must clearly mark which
  numbers come from stub mode (plumbing only) and which come from a
  live run (real signal).
- One more file under the ADR 0005 allowlist
  (`reports/synthetic_judge.aggregate.json`). Mirrors the existing
  exception for `reports/external_baselines.json` (ADR 0009).

**Constraints (unchanged)**

- Public CI must not call out to any external LLM. Enforced by
  convention (CI runs `BIDMATE_SYNTHETIC_JUDGE_BACKEND=stub` by
  default) plus by omission of `make synthetic-judge` from
  `pr-eval.yml` and `make smoke`.
- Aggregate-only commit boundary is enforced by the
  `judge_synthetic_summary` API — only the aggregate dict has the
  shape `write_text` writes to the committed path; the per-case
  local payload writes to the git-ignored path.

## Alternatives considered

- **Live judge in public CI behind a feature flag.** Rejected for
  the same reason as ADR 0006: ADR 0004 reproducibility +
  unjustified per-PR token spend on cases that are mostly crisply
  discriminable.
- **Deterministic semantic similarity (e.g. cosine on embeddings).**
  Rejected: this measures *topical relevance*, not *faithfulness*
  — it cannot tell a faithful summary apart from a hallucinated
  one that uses the right vocabulary.
- **Refactor `scripts/llm_judge.py` to handle both surfaces.**
  Rejected: doubles the blast radius of any change to the
  real-data judge (which is load-bearing for the ADR 0006 commit
  boundary). The two judges share ~100 lines of prompt + backend
  dispatch; the duplication is the cheaper option. If a third
  judge surface appears, revisit and extract `eval/judge_common.py`.
- **Only report `faithfulness`; skip `answer_relevance`.** Rejected:
  the RAGAS-style two-metric pair (faithfulness + answer relevance)
  is what reviewers expect to see, and the marginal cost of asking
  the judge for both in one prompt is zero.
