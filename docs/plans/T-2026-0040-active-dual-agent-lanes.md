# Plan: T-2026-0040 Active-loop dual-agent lanes (registry v2 scaffold)

- Status: review
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0040`
- Related issue / PR: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- Related ADR: [ADR 0080](../adr/0080-active-loop-registry-v2-dual-agent-lanes.md)
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

The merged `active-loop` ships `four-role` + `expanded-eight` topologies and the
Conservative Gate, but has no layer for Claude and Codex to collaborate inside a
session. There is nowhere in the registry to record which agent ran, how Work
Unit (WU) balance is accumulating, or which session may write. Without this, the
"8 sessions × Claude/Codex lane" operating model the user wants cannot be built.

## Current Behavior

`reports/agent_loop/active/session_registry.json` is `schema_version: 1`: a list
of single-agent session dicts (`session_id`, `role`, `status`, `task_id`,
`branch`, `last_heartbeat`, `heartbeat_state`, `lease_expires_at`,
`next_command`). `leases.json` carries one Implementer write lease. The
Conservative Gate (`_active_role_status_ok`) blocks `--execute` until required
reviewer/auditor sessions report a pass-class heartbeat. There is no lane,
agent-mix, or gate-policy field anywhere.

## Desired Behavior

Registry `schema_version: 2` that layers dual-agent **lanes** onto the existing
topologies, observable via:

```bash
python3 scripts/agent_loop.py active-loop --mode full-ship \
  --topology expanded-eight --agent-mix claude=5,codex=5 --dry-run --from-git
```

producing per-session `lanes{claude,codex}` + `write_lease_owner` + `ship_gate`,
top-level `gate_policy:"conservative"` + `agent_mix`, and a
`reports/agent_loop/active/agent_mix.json` ledger. `four-role` output unchanged.

## Constraints

- Scope constraints: registry v2 scaffold + dry-run only. No lane execution, no
  writes, no ship in this PR (Phase 2+ work).
- Architecture constraints: dual-agent is a lane policy, not a topology enum.
  `--topology` stays `four-role | expanded-eight`. No `four-role-dual-agent`.
- Compatibility constraints: `sessions` stays a JSON list; v1 lifts to v2 on read;
  `four-role` role set / lease / gate behavior unchanged.
- Eval/privacy constraints: ledger stays gitignored + privacy-safe (ADR 0005).
- Tooling/CI constraints: reuse `_governance.is_load_bearing` SSoT; do not add a
  parallel load-bearing glob list.
- Non-goals: lane adapters, WU accounting math, patch/mutating/ship phases.

## Architecture Impact

- Affected modules or docs: `scripts/agent_loop.py`, `tests/test_agent_loop.py`,
  `docs/operations/active-agent-loop.md`, `docs/adr/0080-*.md`.
- Affected contracts or invariants: active-loop registry/lease shape (now v2).
- Load-bearing paths: none. `scripts/agent_loop.py` is intentionally **not** added
  to `LOAD_BEARING_PATHS` this phase (advisory dry-run; deferred to Phase 5).
- ADR required: yes — ADR 0080 fixes the v2 coordination/measurement surface.
- Backward compatibility expectation: v1 registries lift cleanly; four-role
  callers unaffected.

## Affected Interfaces

- CLI/API/config: `active-loop --agent-mix claude=N,codex=N`;
  `session-heartbeat --agent claude|codex`.
- Input data: existing ledger (lifted) + `--from-git` changed files.
- Output artifacts: v2 `session_registry.json`, `leases.json` (+`lease_type`,
  `active_agent`), new `agent_mix.json`, topology-aware `active_loop.md`.
- Docs/review surfaces: ops doc "Dual-Agent Lanes" section + ADR 0080.
- Tests/eval entrypoints: `tests/test_agent_loop.py`.

## Data / Eval Impact

- Surface: none (advisory orchestration ledger; not an eval surface).
- Data boundary: no data touched; ledger gitignored + privacy-safe.
- Allowed claim: "registry v2 contract + dry-run scaffold landed."
- Disallowed claim: any retrieval/eval performance claim.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. `scripts/agent_loop.py`: registry v2 (schema_version, lanes, write_lease_owner,
   ship_gate, gate_policy, agent_mix), v1->v2 lift, `--agent-mix`, `--agent`
   lane heartbeat, `agent_mix.json` writer, topology-aware `active_loop.md`.
2. `tests/test_agent_loop.py`: pin v2 contract + assert four-role unchanged.
3. `docs/operations/active-agent-loop.md`: add "Dual-Agent Lanes (registry v2)".
4. `docs/adr/0080-*.md` + `docs/adr/README.md`: decision record + index row.

## Acceptance Criteria

- [ ] expanded-eight dry-run emits 8 sessions, each with claude+codex lanes; one
      Implementer write lease (`lease_type:"write"`, `active_agent:null`).
- [ ] registry `schema_version==2`, `gate_policy=="conservative"`, `agent_mix`
      target reflects `--agent-mix`.
- [ ] four-role dry-run unchanged in role set, lease ownership, and gate behavior.
- [ ] v1 registry lifts to v2 on read.
- [ ] `tests/test_agent_loop.py` green; ADR 0080 verifies-key resolves clean.

## Validation Strategy

Commands that must be run:

```bash
python3 -m py_compile scripts/agent_loop.py scripts/ai_next_actions.py
python3 -m pytest tests/test_agent_loop.py -q
python3 scripts/agent_loop.py active-loop --mode full-ship --topology expanded-eight --agent-mix claude=5,codex=5 --dry-run --from-git
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: `tests/test_agent_loop.py` all pass (105 merged + new v2 tests).
- Generated or updated artifact: v2 `session_registry.json` + `agent_mix.json`.
- Reviewer checklist or manual inspection: four-role parity; lane scaffold shape.
- Explicitly not validated, with reason: lane execution / WU math (Phase 2).

## Rollback Strategy

Revert the PR. The ledger under `reports/agent_loop/active/` is gitignored and
regenerated on the next tick, so no committed data is lost. v1 registries remain
readable (lift is read-only). Do not delete `docs/adr/0080-*.md` — mark Superseded
if reversed (ADR files are never deleted).

## Failure Modes

- Failure mode: a v1 consumer chokes on v2 fields. Detection signal: test failure
  / KeyError. Stop condition: keep `sessions` a list + additive fields only.
- Failure mode: agent_mix.json written outside repo_root in tests. Detection
  signal: test path assertion. Stop: `_active_path` remap added for the new path.

## Observability

- `tests/test_agent_loop.py` (CI gate via `bash scripts/test.sh`).
- `reports/agent_loop/active/{session_registry,leases,agent_mix}.json` shape.
- ADR verification lint: `_governance.lint_adr_verification`.

## Reviewer Notes

Attack first: four-role behavioral parity (must be unchanged), the v1->v2 lift
correctness, and that no write/ship path was added. Confirm dual-agent is a lane
policy (no new topology enum) and that agent_loop.py was deliberately kept out of
LOAD_BEARING_PATHS for this phase (ADR 0080 alternatives).

## Phased roadmap (north star)

This task is PR1 of a 6-PR initiative on issue #1588. Subsequent phases
(`T-2026-0041..0045`) are backlog pending Phase 1-2 validation:

- PR2 (`T-2026-0041`): read-only Claude/Codex turn adapters + WU accounting.
- PR3 (`T-2026-0042`): patch-proposal + lease `active_agent` borrow + scratch worktree.
- PR4 (`T-2026-0043`): mutating-writer + claimed-files enforcement hook.
- PR5 (`T-2026-0044`): Orchestrator-only ship-executor + gate evidence (promote
  agent_loop.py to LOAD_BEARING here).
- PR6 (`T-2026-0045`): full `active-agent-loop.md` ops-doc rewrite.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27

- Role: Implementer
- State: PR1 implementation + tests + ADR 0080 + ops-doc section complete;
  validating before opening PR on issue #1588.
- Next: run validation suite, open PR (Closes #1588), then Phase 2 (T-2026-0041).
```
