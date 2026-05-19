---
name: ship-pr
description: |
  Ship the current worktree's changes as a single PR while honouring ADR 0007 (issue-first, convention-matched branch) and CLAUDE.md's `## Autonomy & Approvals` rule. Bundles three friction-prone steps into one workflow: ADR number reservation (avoids concurrent-worktree collisions), stacked-dependent audit (refuses `--delete-branch` on a base with open children), and explicit-approval gates at push + merge.

  Trigger phrases: "PR 만들어줘", "이거 스택해서 올려", "ADR 쓰고 PR 열어", "ship", "출하", "PR 올려줘", "이 변경 PR로 가자". Trigger even if the user does not say "skill" — driving a change to a merged PR is exactly this skill's scope. Also trigger when the user explicitly references stacked PRs or ADR-then-PR sequencing.

  Do NOT trigger for: bare `git push` or `git commit` requests (skill overhead too high), `make ship-arm` Stop-hook auto-ship runs (different surface, see `docs/operations/auto-ship.md`), or post-merge follow-up tasks. The two ship surfaces are mutually exclusive — never arm `ship-arm` while running this skill.
---

# /ship-pr — Stacked-PR safe-shipping workflow

ADR-aware, approval-gated single-PR shipping. The skill replaces an ad-hoc sequence of `gh issue create` / `gh pr create` / `gh pr merge` calls with one ordered workflow whose dangerous steps require explicit user go-ahead.

## Scope

- One PR per invocation. For a multi-PR stack, the user re-invokes this skill per PR (each call closes one issue).
- Does NOT replace `make ship-arm`. The Stop-hook pipeline (`docs/operations/auto-ship.md`) is fully autonomous; this skill is explicitly gated. Pick one.
- Does NOT auto-write tests — local gate (step 6) just runs them. If tests are missing for a behavior change, surface that and ask the user.

## Workflow

0. **Mutex guard (issue #1043).** Before any other step, check that `.claude/.ship-armed` does NOT exist. If it does, refuse and tell the user to run `make ship-disarm` first — the two ship surfaces are mutually exclusive and `make ship-arm` is currently active. Then `touch .claude/.ship-pr-active` so `make ship-arm` will refuse if invoked while this skill is running. The cleanup (step 13) removes the marker; if the skill aborts, the marker auto-expires after 6h (`_ship_arm.py` stale-marker safety).

1. **Scope confirmation.** Ask the user (inline or via `AskUserQuestion`): "Which issue does this PR close, and what's the one-line summary?" If no issue exists yet, propose a title + body and require **explicit approval** before `gh issue create`.

2. **ADR-necessity check.** Does this change remove or replace a load-bearing decision (baseline / pipeline / answer contract / eval surface — see `docs/adr/README.md` criteria)? If yes → steps 3-5. If no → jump to step 6.

3. **Reserve ADR number.** Print BOTH:
   - `ls docs/adr/ | tail -10` (highest existing number on disk)
   - `gh pr list --search "ADR" --state open --json number,title,headRefName` (open PRs claiming an ADR number)

   Propose `max(existing) + 1` and the slug. Wait for **explicit user confirmation** before writing the file. Concurrent worktrees have produced 3 collisions in the last 4 days — never skip this step.

4. **Author the ADR.** Create `docs/adr/<NNNN>-<slug>.md` with Status / Context / Decision / Consequences / Alternatives. Link related ADRs by number.

5. **Update SSoT if load-bearing path changes.** If the change touches files in `scripts/_governance.py` `LOAD_BEARING_PATHS`, update the list there first (single source of truth read by `.githooks/pre-push` + the §5b CI gate).

6. **Local gate.** Run `bash scripts/test.sh` (pytest -q) and `ruff check .`. On failure, stop and report exactly which test / lint rule failed — ask the user whether to fix in this PR or open a follow-up.

7. **Branch convention check.** Run `python3 scripts/check_branch_and_issue.py --branch "$(git rev-parse --abbrev-ref HEAD)" --check-issue`. If the branch name violates `<type>/issue-<N>[-<slug>]` (ADR 0007), propose a rename and apply `git branch -m` only with explicit approval.

8. **PUSH GATE (explicit approval required).** Show the user the exact command:
   ```
   git push -u origin <branch>
   ```
   Wait for "진행" / "go" / "push it" / equivalent **explicit go-ahead**. Short interrogatives like "push?" are questions — answer them, do not act.

9. **Open PR.** Fill every section of `.github/pull_request_template.md`. Write "N/A — <reason>" rather than deleting any section. If a load-bearing path changed, populate §5b with the output of `make real-eval-delta`. PR title: imperative mood, ≤70 chars.

10. **CI wait (only if user asked).** If the user said "wait for CI" or "ping me when green", run `gh pr checks <N> --watch --interval 30`. Otherwise, return the PR URL and stop — let the user trigger the next step.

11. **STACKED-DEPENDENT AUDIT (critical, do not skip).** Before any merge: run

    ```
    gh pr list --base <head-branch-of-this-PR> --state open \
      --json number,title,headRefName
    ```

    - Empty array → `--delete-branch` is safe to include.
    - Non-empty → the branch has stacked dependents. Two recovery options:
      - **(a)** Drop `--delete-branch` from the merge command (the dependents survive but the base branch lingers — fine for a short-lived stack).
      - **(b)** Rebase each dependent onto main first: `gh pr edit <M> --base main`, then re-run this step.

    Show the user the dependent list. Wait for them to pick (a) or (b). Never auto-choose.

12. **MERGE GATE (explicit approval required).** Display the merge command literally — including the resolved `--delete-branch` flag from step 11. Example:
    ```
    gh pr merge 493 --squash --admin                   # stacked dependents present
    gh pr merge 493 --squash --admin --delete-branch   # no dependents
    ```
    Wait for explicit go-ahead. Then execute.

13. **Aftermath.** `git checkout main` (if the worktree owns main) or `git fetch origin main` + branch advance (worktree case). **Remove the mutex marker** (`rm -f .claude/.ship-pr-active`) so `make ship-arm` is unblocked. If the user has another PR stacked on top, prompt them to re-invoke the skill for the next layer (which re-touches the marker at step 0).

## Approval-gate language

Treat these as **explicit go-ahead** (proceed):

- 한국어: "진행", "ㄱㄱ", "ㅇㅋ", "오케이", "ok", "go", "ship it", "merge it", "push it"

Treat these as **questions** (answer, do not act):

- 한국어: "머지?", "PR?", "올릴까?", "ㅇㅇ?", "?", "right?"
- 영어: "merge?", "ship?", "ready?", "now?"

When uncertain → ask, don't act.

## When the user pushes back

- "그냥 한 번에 다 진행해" → Run steps 1-13 in sequence but still print each gate's intent line ("PUSH executing", "MERGE executing") so the user can interrupt within ~5s. Never collapse gates 8 + 11 + 12 into a single unattended action.
- "ADR 안 만들어도 돼" → Confirm the change is not load-bearing per `scripts/_governance.py --is-load-bearing <path>`. If it is, push back with the load-bearing path that triggered ADR-necessity.
- "stacked PR 그냥 닫혀도 돼" → Acceptable, but show the cost explicitly: "If `--delete-branch` is used, PR #M will auto-close and need recreation. Recovery cost ~5 min per dependent (#423→#431 precedent)." Then take whatever the user picks.

## References

- ADR 0007 — branch + issue convention.
- `CLAUDE.md` `## Autonomy & Approvals`, `## Communication`, `## Core principles` (ADR-number-reservation rule), `## Prohibited` (`--delete-branch` policy).
- `docs/operations/auto-ship.md` — `make ship-arm` Stop-hook automation (mutually exclusive with this skill).
- `scripts/_governance.py` — load-bearing path SSoT (used in step 5 and step 2's ADR-necessity check).
- `scripts/check_branch_and_issue.py` — branch convention validator (step 7).

## What this skill does NOT do

- Does NOT write code, fix tests, or refactor — the user finishes the change before invoking.
- Does NOT bulk-merge multiple PRs. One invocation = one PR.
- Does NOT recover from CI failure automatically — surfaces the failure and asks.
- Does NOT call `gh pr merge` without the stacked-dependent audit in step 11 — even if the user asks to skip it.
