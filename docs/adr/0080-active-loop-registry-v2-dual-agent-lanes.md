# 0080: Active-loop registry v2 + per-session Claude/Codex lanes

- **Status**: accepted
- **Date**: 2026-05-27
- **Deciders**: User, Claude Code as implementer
- **Related**: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588), [active-agent-loop ops doc](../operations/active-agent-loop.md), [ADR 0007](./0007-issue-linked-branch-naming.md), [ADR 0066](./0066-codex-pr-adversarial-review.md), [ADR 0079](./0079-agent-gated-offline-online-rfp-eval-loop.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)

## Context

`agent_loop.py active-loop` already ships two session topologies — the default
`four-role` and the optional `expanded-eight` — plus the Conservative Gate that
only lets `--execute` call the ship runner when the required reviewer/auditor
sessions report a pass-class heartbeat. What it does not have is a layer that lets
Claude and Codex actually collaborate *inside* those sessions.

The operating model the user wants is: 8 durable role sessions, each able to run a
Claude lane and a Codex lane (up to 16 lanes, not 16 simultaneous workers); only
ship-blocking core roles enforce the gate; Planner/Experiment are idle/on-demand
and non-blocking; only the Implementer owns the default write lease; and the
Claude:Codex split is balanced by Work Unit (WU) over a rolling window, not by
session count. Crucially, dual-agent is meant to be a *lane policy*, not a third
topology — adding a `four-role-dual-agent` enum would fork the topology table and
the gate logic for no benefit.

The registry that backs all of this (`reports/agent_loop/active/session_registry.json`)
is `schema_version: 1`: a list of single-agent session dicts with no place to
record which agent ran, how WU is accumulating, or which session may write. The
contract has to grow without breaking the merged `four-role` behavior or its tests.

## Decision

Introduce registry `schema_version: 2` that layers Claude/Codex lanes onto the
existing topologies. Dual-agent is expressed purely as a lane policy; the
`--topology` enum stays `four-role | expanded-eight`.

Per-session additions (`sessions` stays a JSON **list** for back-compat):

- `lanes`: `{claude: {...}, codex: {...}}`, each lane carrying `agent`, `status`,
  `current_turn`, `wu_spent_rolling`.
- `write_lease_owner`: `true` only for the `Implementer` session.
- `ship_gate`: the session's Conservative-Gate class — `lease-owner`,
  `blocking`, `non-blocking`, or `control-plane`.

Top-level additions:

- `gate_policy: "conservative"`.
- `agent_mix`: `{target, unit: "work_unit", window: {type: "rolling_tasks", size},
  max_allowed_skew_wu}`, the WU-balance policy. The CLI accepts
  `--agent-mix claude=5,codex=5`, and the rolling ledger lives in
  `reports/agent_loop/active/agent_mix.json`.

Compatibility and surface rules:

- A v1 registry is lifted to v2 on read (lanes/`write_lease_owner`/`ship_gate`
  synthesized, `gate_policy`/`agent_mix` defaulted). `four-role` output is
  unchanged in role set, lease ownership, and gate behavior.
- `session-heartbeat --agent claude|codex` updates a single lane; omitting
  `--agent` keeps the prior session-level heartbeat.
- The implementer write lease gains `lease_type: "write"` and `active_agent`
  (null until a lane borrows it in a later phase; Claude and Codex never hold it
  at once).
- `scripts/agent_loop.py` is **not** promoted to `LOAD_BEARING_PATHS` in this
  phase. At Phase 1-2 the loop only writes an advisory dry-run ledger and never
  touches the retrieval/verifier/answer/eval runtime, so §5b real-data delta
  would be a perpetual vacuous attestation. The contract is instead pinned by
  this ADR plus the `tests/test_agent_loop.py` suite. Promotion is deferred to
  the Phase 5 Orchestrator-only ship-executor, where a bug carries real ship
  blast radius.

This ADR fixes the v2 registry/lease/agent_mix contract as a new reviewer-facing
coordination surface. Read-only lane execution adapters and WU accounting land in
Phase 2; patch-proposal, mutating-writer, and ship-executor isolation follow in
Phases 3-5.

## Consequences

- Reviewers and downstream tooling can rely on a stable v2 shape: lanes,
  `ship_gate`, `write_lease_owner`, `gate_policy`, and `agent_mix` are contractual.
- `four-role` callers and their tests keep working because `sessions` stays a list
  and v1 is lifted, not rejected.
- WU becomes the unit of Claude:Codex balance, so later phases measure mix skew
  against `agent_mix.json` rather than counting sessions.
- The active ledger (`session_registry.json`, `leases.json`, `agent_mix.json`,
  `events.jsonl`) remains gitignored and must stay privacy-safe per ADR 0005: no
  raw private question/answer text, `doc_id`, `chunk_id`, filenames, prompt bodies,
  or absolute private paths.
- Because agent_loop.py stays out of LOAD_BEARING_PATHS, this PR needs no §5b; the
  load-bearing decision is revisited when the loop can actually ship (Phase 5).

## Alternatives considered

- **Make `sessions` a map keyed by session id.** Rejected: it would rewrite ~10
  merged tests and the `_write_active_registry` helper for no behavioral gain. A
  list plus per-item `lanes` preserves back-compat and the "four-role unchanged"
  requirement.
- **Add a `four-role-dual-agent` topology enum.** Rejected: dual-agent is
  orthogonal to topology. Forking the enum would duplicate the topology table,
  gate map, and next-command logic. A lane policy layered on both topologies is
  simpler and keeps the gate single-sourced.
- **Introduce a parallel `LOAD_BEARING_GLOBS` list for agent_loop.py.** Rejected:
  CLAUDE.md mandates `_governance.LOAD_BEARING_PATHS` as the single machine-readable
  source. A second list would drift. (And we defer adding agent_loop.py to that one
  list until Phase 5.)
- **Promote agent_loop.py to load-bearing now.** Rejected for this phase: at
  dry-run/read-only the loop has no model-path blast radius, so §5b would carry no
  signal. Deferred to the ship-executor phase.

## Verification

<!-- verifies-key: docs/operations/active-agent-loop.md:Dual-Agent Lanes -->
<!-- verifies-key: docs/operations/active-agent-loop.md:ship_gate -->
<!-- verifies-key: docs/operations/active-agent-loop.md:agent_mix -->
