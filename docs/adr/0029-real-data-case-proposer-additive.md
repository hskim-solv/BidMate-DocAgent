# 0029: Real-data case proposer as additive semi-supervised eval-set growth

- **Status**: proposed
- **Date**: 2026-05-13
- **Related**: extends [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) / [ADR 0006](./0006-llm-judge-on-real-data-only.md); reuses backend pattern of [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0012](./0012-llm-judge-on-public-synthetic.md); preserves [ADR 0001](./0001-preserve-naive-baseline.md) / [ADR 0003](./0003-structured-answer-citation-contract.md) / [ADR 0004](./0004-verifier-retry-policy.md) / [ADR 0008](./0008-evidence-boundary.md); calibration mirrors [ADR 0016](./0016-judge-human-agreement.md)
- **Deciders**: hskim

## Context

The private real-data eval surface
([`eval/real_config.example.yaml`](../../eval/real_config.example.yaml))
caps at whatever the human labels — currently N=100. Each case is an
8-field dict (`query`, `query_type`, `expected_doc_ids`,
`expected_terms`, `expected_citation_terms`, `expected_claim_targets`,
`answerable`, `id`) that costs 5–15 minutes to author. Scaling to
N=200+ is a labeling-throughput problem, not an infrastructure
problem.

[ADR 0005](./0005-eval-split-public-synthetic-private-local.md) locks
case bodies out of the commit boundary (aggregate-only). [ADR 0006](./0006-llm-judge-on-real-data-only.md)
allows LLMs on the real-data surface but only as a *judge* — a
second-opinion read of an existing answer. "LLM proposes a case
candidate, human reviews" is not in either ADR's scope; doing it
without an explicit decision would silently mix machine-generated
labels into a surface that ADR 0005 treats as ground truth.

The pattern that fits is ADR 0011's *additive ablation*: introduce a
new surface (stub-default backend, opt-in live backend) alongside the
existing one without touching its contract. ADR 0012 already applied
this to the synthetic judge. The same shape applies to a real-data
case proposer, with two extra constraints: case bodies still cannot
cross the commit boundary (ADR 0005), and the human reviewer is the
gate that decides what enters `eval/real_config.local.yaml`.

## Decision

Add a **case proposer** as an additive, semi-supervised input surface
to the real-data eval. The proposer generates candidate case dicts
that match `eval/real_config.example.yaml`'s 8-field schema; a human
reviews each candidate (accept / edit / reject) before any case is
appended to `eval/real_config.local.yaml`.

### Contract

- **Input**: `data/data_list.csv` metadata + the top-3 chunks of each
  seed document from `data/index/real100/index.json`. The `live`
  backend may consume chunk bodies; the deterministic fields
  (`expected_doc_ids`, `answerable`) are *always* derived from the
  source row and `query_type`, never from a model response.
- **Output (per case)**: superset of the 8-field schema with two
  meta fields:
  ```yaml
  - id: proposed_<YYYYMMDD>_<NNN>
    source: "proposed-then-reviewed"          # vs. "human"
    proposer_meta:
      backend: "stub" | "openai_compatible"
      model: "<model-id or 'stub'>"
      seed_doc_id: "<doc-id from index>"
      generated_at: "<ISO8601Z>"
      proposer_version: 1
    # ... 8 schema fields ...
  ```
  Both `source` and `proposer_meta` are stripped on append to
  `eval/real_config.local.yaml`, so the active config stays a
  byte-equal subset of the existing schema.
- **Committable aggregate** (`reports/proposed/proposer.aggregate.json`,
  ADR 0005 allowlist):
  ```json
  {
    "schema_version": 1,
    "backend": "stub" | "openai_compatible",
    "n_proposed": 30, "n_reviewed": 25, "n_accepted": 18,
    "proposer_accept_rate": 0.72,
    "field_edit_rate": {"query": 0.40, "expected_terms": 0.65, ...},
    "by_query_type": {"single_doc": {...}, "abstention": {...}}
  }
  ```
  Per-case proposed / reviewed yaml stays under
  `reports/proposed/*.local.yaml` (gitignored).

### Backend pluggability

`eval/case_proposer.py` mirrors `eval/synthetic_judge.py`'s backend
dispatch:

- `stub` (default) — deterministic; emits metadata-driven template
  queries (`사업기간` / `사업예산` / abstention) from `data_list.csv`
  rows. Byte-equal across runs. Used by tests and CI plumbing.
- `openai_compatible` — generic OpenAI-compatible endpoint. Reuses
  the existing `BIDMATE_JUDGE_API_KEY` / `BIDMATE_JUDGE_MODEL` /
  `BIDMATE_JUDGE_BASE_URL` env vars (a single model can serve both
  the judge and the proposer); backend selection is a separate var
  (`BIDMATE_CASE_PROPOSER_BACKEND`) so the two surfaces toggle
  independently. Chunk bodies pass through
  `neutralize_instruction_patterns` + `EVIDENCE_BOUNDARY`
  (ADR 0008) before reaching the prompt.

### Two-stage human gate

- `make case-propose` writes
  `reports/proposed/proposed_cases.local.yaml`.
- `make case-review` is an interactive CLI that walks each candidate,
  shows a yaml diff, and records `approved: true|false` plus any
  edits to `reports/proposed/reviewed_cases.local.yaml`.
- `make case-promote` performs an *idempotent* append of approved
  cases to `eval/real_config.local.yaml`, skipping any `id` already
  present. The promote step is explicit (not auto-triggered by
  review) so the human confirms one more time.
- `make case-proposer-aggregate` computes
  `proposer.aggregate.json` from the reviewed yaml.

### Statistical hygiene

- The active `run_eval.py` aggregate **does not** expose the `source`
  field (`human` vs `proposed-then-reviewed`). All cases in
  `eval/real_config.local.yaml` are treated as equally authoritative
  by the downstream pipeline. The mix ratio is only visible in
  `proposer.aggregate.json` and in the README's two-column
  "100 hand + N proposed-reviewed" rendering. This keeps the headline
  eval surface honest while making the labeling provenance auditable.
- `proposer_accept_rate` is the calibration knob, parallel to
  ADR 0016's `judge_human_agreement`: < 0.5 means the proposer is
  systematically producing rejected cases — backend / prompt
  rethink, not a numeric gate.

### Cadence

Manual, like the rest of the real-data cycle. The user runs
`make case-propose && make case-review && make case-promote`
when they want to grow the case set, then `make real-eval` re-runs
the pipeline over the (now larger) `eval/real_config.local.yaml`.

## Consequences

**Wins**

- Real-data N can grow past 100 without breaking ADR 0005 — case
  bodies still never cross the commit boundary.
- Per-case labeling time drops from 5–15 min (full hand-label) to
  1–3 min (review + edit) once the proposer is competent, with
  `proposer_accept_rate` measuring how competent.
- One more application of ADR 0011's "stub-default + opt-in live"
  pattern (now: 0011 synthesis, 0012 synthetic judge, 0013
  observability, 0017 metadata extraction, 0023 HyDE, 0027 LoRA,
  0028 security screen, 0029 case proposer). Reviewers see the same
  shape eight times — the additive-pluggable idiom is the project's
  default.
- `proposer.aggregate.json` is committable, so the growth from N=100
  to N=130, N=150, ... is chronological in git log (mirrors ADR 0005
  history pattern via `make real-eval-history-render`).

**Costs**

- One more file under the ADR 0005 allowlist
  (`reports/proposed/proposer.aggregate.json`). Mirrors the existing
  exceptions for `synthetic_judge.aggregate.json` (ADR 0012) and
  `external_baselines.json` (ADR 0009).
- Two-stage human gate is more steps than "edit the yaml directly".
  Mitigated by `make case-propose` skipping any seed doc that
  already has 2+ proposed cases in the past 30 days, so the user
  doesn't re-review identical templates.
- Prompt-injection surface expands once the live backend lands
  (PR3); the chunk-body sanitizer reuse from ADR 0008 is the
  mitigation but adds one more callsite to keep in sync.

**Constraints (unchanged)**

- ADR 0001 byte-identity of the naive baseline golden
  (`tests/data/naive_baseline_top_k.json`). The proposer touches
  only `eval/real_config.local.yaml` (private) and never
  `eval/config.yaml` (public synthetic).
- ADR 0003 answer contract. The proposer is upstream of
  `run_rag_query`; it produces eval *inputs*, not answer outputs.
- ADR 0004 deterministic verifier. Public CI never invokes the
  proposer (no `make case-propose` in `pr-eval.yml` or `make smoke`).
- ADR 0005 aggregate-only commit boundary. Case bodies stay
  gitignored under `reports/proposed/*.local.yaml`; only the
  metric aggregate crosses.
- ADR 0008 evidence boundary. PR3's live backend passes chunks
  through the same sanitizer as `scripts/llm_judge.py`.

## Alternatives considered

- **Skip the proposer; just hand-label more cases.** Rejected:
  labeling at 5–15 min/case caps the practical N around 100 — even
  one work-day of effort only adds ~30 cases, and the marginal
  case has the lowest value (most novel failure modes already
  caught). The proposer's 1–3 min/case review economics make N=200+
  realistic.
- **Auto-generate cases and skip the human gate.** Rejected: ADR 0006
  pinned the LLM-as-second-opinion principle for the real-data
  surface. Allowing an LLM to produce *both* the question and the
  expected labels would mean the eval set is grading itself —
  exactly the failure mode ADR 0006 was written to prevent.
- **Use the proposer on the public synthetic surface instead.**
  Rejected: synthetic cases are crisply discriminable by
  construction (ADR 0006 §Alternatives); the marginal case there
  has near-zero value. The labeling bottleneck is real-data only.
- **Reuse `eval/synthetic_judge.py` to also propose cases.**
  Rejected: doubles the blast radius of any change to either
  surface. The two scripts share ~50 lines of backend dispatch; the
  duplication is the cheaper option until a third LLM surface
  appears (then extract `eval/llm_backend.py`).
- **Train a deterministic proposer from past hand-labeled cases.**
  Premature; revisit if `proposer_accept_rate` on the
  `openai_compatible` backend plateaus below 0.5 across multiple
  prompt iterations.
