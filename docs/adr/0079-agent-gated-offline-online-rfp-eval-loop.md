# 0079: Agent-gated offline/online RFP eval loop

- **Status**: accepted
- **Date**: 2026-05-26
- **Deciders**: User, Codex as conservative agent gate
- **Related**: [#1529](https://github.com/hskim-solv/BidMate-DocAgent/issues/1529), [agent-gated RFP eval loop](../evaluation/agent-gated-rfp-eval-loop.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md)

## Context

The evaluation loop needs to continue across two environments: offline closed
network runs where external APIs are unavailable but downloaded models, GPU, and
local LLM judges are allowed; and online runs where external judges, models, APIs,
and private RFP text egress are allowed. Existing governance separates public
fixture smoke, public synthetic benchmark, and private real-eval surfaces, but it
does not define how those surfaces map onto offline/online execution.

The previous workflow also treated private real-eval decisions, performance
claims, architecture tradeoffs, issue/PR close, merge, push, and branch deletion
as human gates. The user now wants those decisions delegated to Codex under a
conservative policy gate, while preserving the repo's eval validity and privacy
discipline.

## Decision

Codex will act as a conservative agent gate for the offline/online RFP evaluation
loop, using private real-eval as the required claim-bearing surface and adopting
metric suites by versioned evidence rather than by a single headline score.

Specifics:

- Offline allows downloaded models, GPU, and local LLM judges, but no external
  API calls.
- Online allows external judges, models, APIs, and private RFP raw text egress,
  with provider/model/date/payload-class provenance.
- RFP success is measured as a suite: retrieval recall, grounding, citation
  precision, claim-citation alignment, comparison coverage, abstention
  calibration, numeric/date/condition accuracy, and human/judge agreement.
- A single headline score is a triage aid, not a merge/block contract.
- Claim-bearing metric adoption requires private real-eval aggregate evidence.
- Ambiguous cases default to draft, no performance claim, follow-up issue, or
  fail-closed handling.
- Existing `human-gated-*` CLI names remain as compatibility names, but their
  policy meaning is "explicit conservative gate acknowledgment."

## Consequences

- The loop can keep moving without asking the user for every merge, claim,
  private eval, or cleanup decision.
- Agent decisions become auditable because the acceptance criteria live in a
  committed policy document.
- Private real-eval becomes mandatory for performance evidence, increasing run
  cost and provenance requirements.
- Online private-data egress is permitted by policy, so every online run must
  record provider/model/payload provenance and keep raw private outputs out of
  committed artifacts.
- Metric changes must explain whether they are offline/online-compatible and how
  they relate to human or approved judge signals.

## Alternatives considered

- **Keep human gates.** Rejected because the target operating model is a
  persistent loop where Codex can continue under a conservative policy without
  stopping for routine approvals.
- **Use a single composite score.** Rejected because RFP QA can improve retrieval
  while degrading citation, abstention, or numeric/date correctness; a suite keeps
  failure modes visible.
- **Allow public synthetic benchmark as claim evidence.** Rejected because ADR
  0005 already restricts real-world performance claims to private/internal eval
  aggregate evidence.

## Verification

<!-- verifies-key: docs/evaluation/agent-gated-rfp-eval-loop.md:Metric Suite -->
<!-- verifies-key: docs/evaluation/agent-gated-rfp-eval-loop.md:Agent Gate -->
<!-- verifies-key: docs/evaluation/surface-map.md:Environment Axis -->
