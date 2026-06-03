# Plan: T-2026-0014 Agent gate surface alignment

- Status: review
- Owner role: Maintainer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0014`
- Related issue / PR: Issue #1531 / PR #1532
- Related ADR: ADR 0079
- Created: 2026-05-27
- Last updated: 2026-06-03

## Problem Statement

After ADR 0079, several visible agent-loop surfaces still read as if routine
progress depends on manual human gates. That weakens the intended conservative
agent-gate operating model and leaves subagent role separation as an informal
practice rather than a repeatable planning surface.

## Current Behavior

`scripts/agent_loop.py` already has many local, read-only or gated command
surfaces, but the map, coverage report, command help, and generated briefs mix
legacy human-gate wording with the new policy. The eval policy has ADR 0079
semantics but lacks a concrete role-dispatch rule for Codex subagents.

## Desired Behavior

The loop should present conservative agent gates as the default decision model,
keep legacy command/flag names for compatibility, and expose `role-dispatch` as
a report-only plan for up to 12 role subagents with depth 2.

## Constraints

- Scope constraints: wording and local report tooling only.
- Architecture constraints: no replacement of the existing shipping pipeline.
- Compatibility constraints: keep `human-gated-exec` and `--confirm-human-approved`.
- Eval/privacy constraints: no current `real100_v2` private-eval run and no
  performance claim.
- Tooling/CI constraints: focused agent-loop tests plus doc/link/branch checks.
- Non-goals: no remote mutation behavior change.

## Architecture Impact

- Affected modules or docs: `scripts/agent_loop.py`, `tests/test_agent_loop.py`,
  `docs/evaluation/agent-gated-rfp-eval-loop.md`, `tasks/queue.md`.
- Affected contracts or invariants: legacy command and flag names remain stable.
- Load-bearing paths: none.
- ADR required: no; this implements ADR 0079 wording and tooling surfaces.
- Backward compatibility expectation: existing CLI command names continue to work.

## Affected Interfaces

- CLI/API/config: adds `python3 scripts/agent_loop.py role-dispatch`.
- Input data: optional changed-file list, `--from-git`, PR changed files, owner role.
- Output artifacts: `reports/agent_loop/role_dispatch.md`.
- Docs/review surfaces: eval policy and task queue handoff.
- Tests/eval entrypoints: `tests/test_agent_loop.py`.

## Data / Eval Impact

- Surface: none.
- Data boundary: no data touched.
- Allowed claim: governance/tooling surfaces now align with ADR 0079.
- Disallowed claim: no RFP QA, benchmark, current `real100_v2`
  private-eval, or performance claim.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no, but benchmark/privacy auditor roles are
  included in generated dispatch plans when the changed-file surface requires it.

## Task Breakdown

1. Align visible agent-loop wording with conservative agent gates.
2. Add `role-dispatch` report generation and CLI wiring.
3. Document role dispatch policy and update queue handoff evidence.
4. Add focused tests for map, coverage, and role-dispatch behavior.

## Acceptance Criteria

- [x] Loop map, gate brief, coverage report, and command help use agent-gate wording.
- [x] `role-dispatch` renders max-12, depth-2 subagent dispatch cards without execution side effects.
- [x] Eval policy documents role-dispatch rules and non-delegated decisions.
- [x] Focused validation passes.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 -m py_compile scripts/agent_loop.py
python3 scripts/agent_loop.py role-dispatch --owner-role "Implementer -> Benchmark Auditor -> Reviewer" --from-git
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md tasks/queue.md docs/plans/T-2026-0014-agent-gate-surface-alignment.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused pytest return code 0.
- Generated or updated artifact: `reports/agent_loop/role_dispatch.md`.
- Reviewer checklist or manual inspection: legacy command names unchanged.
- Explicitly not validated: current `real100_v2` private eval, because this
  change makes no metric claim.

## Rollback Strategy

Revert the wording and `role-dispatch` additions in one PR. Do not delete
existing generated reports; they are local evidence artifacts and ignored by the
tracked source tree.

## Failure Modes

- Failure mode: text implies remote mutation can happen without explicit command/flag.
- Detection signal: tests or reviewer finds missing confirmation wording.
- Stop condition or fallback: keep legacy names and fail closed to draft/no-claim.

## Observability

- `reports/agent_loop/role_dispatch.md`
- `reports/agent_loop/automation_coverage.md`
- `python3 -m pytest tests/test_agent_loop.py -q`
- `python3 scripts/check_doc_links.py --check-all --paths ...`

## Reviewer Notes

Attack compatibility first: command names, confirmation flags, and remote
mutation semantics must not change. Then check that subagent dispatch remains a
planning report rather than hidden execution, and that no performance claim is
introduced.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 KST

- Role: Maintainer
- Branch / worktree: chore/issue-1531-agent-gate-surfaces / /Users/hskim/.codex/worktrees/1c21/BidMate-DocAgent
- Issue / PR: #1531 / PR #1532
- Task: T-2026-0014
- Current status: implementation complete; focused validation passed once.
- Files touched: scripts/agent_loop.py, tests/test_agent_loop.py, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/plans/T-2026-0014-agent-gate-surface-alignment.md, tasks/queue.md
- Decisions made: role dispatch is report-only; root session keeps final gate and remote mutation decisions.
- Commands run: focused pytest, py_compile, role-dispatch, doc links, git diff --check, make check-branch
- Results: passed
- Next safe command: git diff --stat
- Open questions: none
- Risks: reviewer should confirm legacy wording is clear enough for compatibility.
```
