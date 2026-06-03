# Plan: T-2026-0018 Codex-runnable auto-ship

- Status: done
- Owner role: Maintainer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0018`
- Related issue / PR: issue #1547 / PR #1548; refresh issue #2102
- Related ADR: N/A - no decision-level change
- Created: 2026-05-27
- Last updated: 2026-06-04

## Problem Statement

`make ship-arm` writes `.claude/.ship-armed` and relies on Claude Code's Stop
hook to run `scripts/claude-hooks/stop-ship.sh`. Codex Desktop sessions can
write the arm file but do not naturally fire that Stop hook, so the implemented
auto-ship loop looks armed while no shipping pipeline runs.

## Current Behavior

- `make ship-start` creates the issue-linked branch.
- `make ship-arm` writes `.claude/.ship-armed` through `_ship_arm.py`.
- `.claude/settings.json` wires Claude Stop events to `stop-ship.sh`.
- `agent_loop.py auto-ship-plan` and `auto-ship-prepare` explain the path but
  do not push, create PRs, wait for checks, or merge.

## Desired Behavior

Codex/non-Claude sessions have one explicit command that arms the same state
file and immediately invokes the same dispatcher. Existing Claude Stop-hook
behavior remains unchanged.

## Constraints

- Scope constraints: do not change merge policy, branch deletion policy, review
  gate policy, or PR body §5b policy.
- Architecture constraints: reuse `_ship_arm.py` and `stop-ship.sh`; do not
  duplicate Stage 1-5 logic.
- Compatibility constraints: `make ship-arm` remains arm-only.
- Eval/privacy constraints: no private data or real-eval execution required.
- Tooling/CI constraints: tests must avoid remote mutations.
- Non-goals: no new scheduler, no draft/CI/review bypass, no policy change.

## Architecture Impact

- Affected modules or docs: `Makefile`, `scripts/claude-hooks/`,
  `docs/operations/auto-ship.md`, tests.
- Affected contracts or invariants: auto-ship still has one dispatcher and one
  arm file contract.
- Load-bearing paths: none.
- ADR required: no, this wires an existing operational path for another client.
- Backward compatibility expectation: existing `make ship-arm` and Stop-hook
  users behave the same.

## Affected Interfaces

- CLI/API/config: add `make ship-run`, `make codex-ship`, and
  `USE_EXISTING_ARM=1`.
- Input data: `.claude/.ship-armed`.
- Output artifacts: unchanged `.claude/.ship-history.log` and
  `.claude/.ship-dryrun.log`.
- Docs/review surfaces: auto-ship operations doc and hook helper inventory.
- Tests/eval entrypoints: focused pytest for runner and dispatcher gates.

## Data / Eval Impact

- Surface: none
- Data boundary: no data touched
- Allowed claim: Codex can invoke the existing auto-ship dispatcher directly.
- Disallowed claim: no claim that CI, review, or merge policy was relaxed.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. Add `_ship_run.py` and Make targets that arm then immediately invoke
   `stop-ship.sh`.
2. Let the dispatcher continue when a clean branch already has an open PR, so
   direct runs can resume CI/review/merge.
3. Update tests and docs for direct runner semantics.

## Acceptance Criteria

- [x] `make ship-run` arms and dispatches through the existing shell pipeline.
- [x] Existing arm files are fail-closed unless `USE_EXISTING_ARM=1` is set.
- [x] Clean branches with an existing PR continue through dry-run CI/review/merge.
- [x] Docs distinguish `make ship-arm` from `make ship-run`.
- [x] Focused tests and branch checks pass.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_ship_run.py tests/test_ship_dispatcher_gates.py tests/test_ship_arm_mutex.py -q
python3 -m py_compile scripts/claude-hooks/_ship_run.py scripts/claude-hooks/_ship_arm.py
python3 scripts/check_doc_links.py --check-all --paths docs/operations/auto-ship.md docs/plans/T-2026-0018-codex-runnable-auto-ship.md tasks/queue.md scripts/claude-hooks/README.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused pytest return code 0.
- Generated or updated artifact: plan and queue entries for T-2026-0018.
- Reviewer checklist or manual inspection: direct runner reuses existing
  dispatcher; no new remote mutation path.
- Explicitly not validated, with reason: no live merge; dry-run tests avoid
  remote mutation.

## Rollback Strategy

Revert `_ship_run.py`, the Make targets, the clean-existing-PR gate change, and
the docs/tests updates. Existing `make ship-arm` behavior is independent and
should continue working because Stop-hook wiring is not changed.

## Failure Modes

- Failure mode: direct runner overwrites an active arm.
- Detection signal: `_ship_run.py` refuses when `.claude/.ship-armed` exists
  unless `USE_EXISTING_ARM=1`.
- Stop condition or fallback: run `make ship-disarm`, inspect
  `.claude/.ship-history.log`, and use `make ship-arm` in Claude Code.

- Failure mode: dispatcher no-ops after PR creation because the local branch is
  clean and has no unpushed commits.
- Detection signal: `stop-ship.sh` logs `nothing to ship` instead of reusing
  the existing PR.
- Stop condition or fallback: run `USE_EXISTING_ARM=1 make ship-run` after the
  existing-PR gate is fixed.

## Observability

- `.claude/.ship-history.log`
- `.claude/.ship-dryrun.log`
- `make ship-status`
- `gh pr list --head <branch>`

## Reviewer Notes

Attack the wrapper/dispatcher boundary first: `_ship_run.py` must not duplicate
shipping policy, and `stop-ship.sh` must only resume clean branches when an
existing PR for the armed branch is visible.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 00:00 KST

- Role: Maintainer
- Branch / worktree: chore/issue-1547-codex-ship-run /
  /Users/hskim/.codex/worktrees/1547/BidMate-DocAgent
- Current status: merged in PR #1548.
- Commands run: python3 -m pytest tests/test_ship_run.py tests/test_ship_dispatcher_gates.py tests/test_ship_arm_mutex.py -q; python3 -m py_compile scripts/claude-hooks/_ship_run.py scripts/claude-hooks/_ship_arm.py; python3 scripts/check_doc_links.py --check-all --paths docs/operations/auto-ship.md docs/plans/T-2026-0018-codex-runnable-auto-ship.md tasks/queue.md scripts/claude-hooks/README.md; git diff --check; make check-branch
- Results: passed
- Next safe command: make ship-status
```
