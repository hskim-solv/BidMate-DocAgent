# Engineering governance

This page is the **single navigation point** for how engineering work
flows through this repo. It ties together the rule book
([`CLAUDE.md`](../CLAUDE.md)), decision records
([`docs/adr/`](./adr/README.md)), tests, evaluation, and
reviewer-facing artifacts.

If you are new to the repo or onboarding a reviewer, start here.

## Where each thing lives

| Concern | Source of truth | Notes |
|---|---|---|
| Coding & review rules | [`CLAUDE.md`](../CLAUDE.md) | Pre-PR checklist, prohibited shortcuts, performance expectations. |
| Multi-agent coordination | [`docs/multi-agent-ownership.md`](./multi-agent-ownership.md) | 7-way ownership split, `rag_core.py` lock holder, conflict-resolution rules when several agents work in parallel. |
| Load-bearing decisions | [`docs/adr/`](./adr/README.md) | One short file per decision; status-tracked. |
| Behavior contracts | [ADR 0003](./adr/0003-structured-answer-citation-contract.md), [`docs/agentic/answer-policy.md`](./agentic/answer-policy.md) | Answer JSON shape, `schema_version`, status values. |
| Eval surfaces | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`eval/config.yaml`](../eval/config.yaml), `eval/*.example.yaml` | Public synthetic is committed; private local is `.gitignore`d. |
| Reviewer-facing metrics | `reports/eval_summary.json`, README headline table | The PR eval delta workflow upserts a PR comment with the diff. |
| Failure analysis | [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md), [`docs/real-data/failure-cases.md`](./real-data/failure-cases.md) | Drives the prioritized backlog. |
| API demo | [`docs/operations/api-demo.md`](./operations/api-demo.md), `api/main.py` | Reviewer playground; never the source of truth for measurement. |
| Issue/PR triage | This page, ["Milestones & issue lifecycle"](#milestones--issue-lifecycle) | Milestones, stale policy, current categorisation snapshot. |

## Change lifecycle

The expected flow for any non-trivial change, written as a checklist
a contributor (human or AI) can walk through:

1. **Open or pick an issue. (Required, ADR 0007.)** Real-data failure
   taxonomy entries (`docs/real-data-failure-taxonomy.md`) and the
   prioritized backlog are the primary feed. Use the templates in
   [`.github/ISSUE_TEMPLATE/`](../.github/ISSUE_TEMPLATE/). The
   branch + PR are required to reference this issue number; the
   convention check (CI) will block merge otherwise.
2. **Decide if it needs an ADR.** Use the criteria in
   [`docs/adr/README.md`](./adr/README.md). Most changes do **not**;
   when in doubt, ask in the issue.
3. **Inspect what exists.** Per `CLAUDE.md` ("Before coding,
   inspect..."). Name the files you read, the functions you intend
   to reuse, and what you found that surprised you.
4. **Branch + worktree if parallel.** Name the branch
   `<type>/issue-<N>[-<slug>]` per ADR 0007 — e.g.
   `feat/issue-79-hybrid-retrieval`. Claude Code's default
   worktree names (`claude/<auto>`) must be renamed before the PR
   (`git branch -m feat/issue-<N>-<slug>`). Two independent tracks
   → two worktrees, two PRs. Coupled tracks → one PR, one branch.
5. **Make the change.** Reuse over invent. One concern per PR.
6. **Add or update tests.** Behavior change without a test is
   presumed accidental. Regressions get a guard test in
   `tests/test_*_regression.py`.
7. **Run the eval locally if relevant.** `make eval` for the public
   synthetic surface. Compare against `main`'s
   `reports/eval_summary.json` if you have it.
8. **Push, open PR.** PR body fills in
   [`.github/pull_request_template.md`](../.github/pull_request_template.md)
   (what / files / risks / tests / eval impact / back-compat / out-of-scope).
9. **CI verifies.** Three checks run on every PR:
   - `Pytest` (in `pr-eval.yml`).
   - `Eval delta vs base` (in `pr-eval.yml`) — upserts a comment with
     the metrics table; expect `·` across the board for non-RAG changes.
   - `Validate branch name + issue link` (in `branch-and-issue-check.yml`,
     ADR 0007) — enforces the convention. Required status check.
10. **Address review.** No mid-review scope creep — open a follow-up
    issue instead.
11. **Merge.** Squash-merge, delete the branch, remove the worktree
    if used.
12. **Update docs** if the change changed something a reviewer needs
    to know (README headline metrics, ADR status, taxonomy entry).

## Milestones & issue lifecycle

Open issues are grouped into milestones so the backlog scans cleanly
and a reviewer can see what is planned vs. parked. Milestones are
manually maintained on GitHub; the snapshot below is illustrative —
the GitHub milestone pages are authoritative.

### Milestones

| Milestone | Purpose | Typical issue kind |
|---|---|---|
| `v3-release` | Concrete work toward the next release of the RAG stack — ingestion v3, retrieval/ranking changes, new core utilities. | `feat`, `fix` that ship behavior. |
| `portfolio-review-readiness` | Reviewer-facing polish: README clarity, case-study narrative, deploy artifacts, structured-output docs, ablation visualisation. | `docs`, `chore`, `eval` work whose audience is the portfolio reviewer. |
| `real-data-evaluation` | Private 100-doc real-data eval health: failures observed in [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md), Korean-specific axes, abstention regressions. | `eval`, `fix` that lands a measurable real-data delta. |

Meta/parent issues (e.g. #118 portfolio review readiness, #187 phase
enhancement backlog) do **not** carry a milestone — they group child
issues which themselves are milestoned.

### Stale-issue policy

- **60 days without activity** → label `stale`. Comment with a one-line
  prompt: "still planned? close or rescope." Triage weekly.
- **90 days without activity after `stale`** → close with a comment
  pointing at the milestone the work would have lived in. Reopen if the
  work is picked up.
- **Never auto-close** — closure is a human decision, the label is the
  automation-friendly signal.

The labels and milestones are managed manually for now; no GitHub
Action wires this. Promotion to automation lands as a separate change
if backlog growth justifies it.

### Snapshot (2026-05-11)

| Milestone | Open issues |
|---|---|
| `v3-release` | #121, #167, #168, #170 |
| `portfolio-review-readiness` | #122, #123, #124, #125, #127, #128, #164, #172 |
| `real-data-evaluation` | #126 |

Issues without a clear home stay milestone-less until categorised.

## How the documents reinforce each other

```
                ┌───────────────────────────┐
                │        CLAUDE.md          │  (the rules)
                └─────────────┬─────────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        ┌──────────┐    ┌──────────┐     ┌──────────┐
        │  ADRs    │    │  Tests   │     │   Eval   │
        │ (why)    │    │ (guard)  │     │ (proof)  │
        └────┬─────┘    └────┬─────┘     └────┬─────┘
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                ┌───────────────────────────┐
                │ Reviewer-facing artifacts │
                │ (README, docs/*, PR diff) │
                └───────────────────────────┘
```

- **CLAUDE.md** says what every change must satisfy.
- **ADRs** record why a load-bearing choice was made, so future
  changes don't unknowingly invert it.
- **Tests** prevent the rules and decisions from silently rotting.
- **Eval** turns the rules and decisions into numbers a reviewer can
  read.
- **Reviewer artifacts** (README, design docs, PR descriptions,
  ablation reports) point back into the above so the system can be
  understood end-to-end without DM'ing the author.

## Anti-patterns this governance is designed to prevent

- Silent contract drift — an answer field disappears and no test
  catches it. *Prevented by:* ADR 0003 + `score_answer_format` in
  `eval/run_eval.py`.
- Headline-metric inflation — README claims a number that no
  artifact backs. *Prevented by:* `scripts/update_readme_metrics.py
  --check` in `make check`, plus the public/private eval split (ADR
  0005).
- Baseline rot — the naive baseline still imports but no one runs
  it. *Prevented by:* `naive_baseline` is a named ablation in
  `eval/config.yaml`; every eval run reports it.
- Decision laundering — a load-bearing choice is buried in a
  refactor PR. *Prevented by:* ADR threshold in `CLAUDE.md` Core
  principles + [`docs/adr/README.md`](./adr/README.md); the PR
  template forces the question.
- Review-time scope creep — a PR grows to include "while I was
  here" fixes. *Prevented by:* "one PR, one concern" in
  `CLAUDE.md`; spawn a follow-up issue instead.

## Governance saves: real incidents prevented

The list above is the *design* — the rules and the guards. This
section is the *evidence*: incidents that actually happened in this
repo, and the hook/ADR/rule that was added afterward so the same
class of failure cannot recur silently.

The point of recording these is to make the governance auditable.
In an AI-assisted workflow where every layer (CLAUDE.md, hooks,
ADRs, eval split) accretes by default, the question a reviewer
should be able to answer in 30 seconds is *not* "is governance
present?" but "did it pay rent?". Each entry below is one rent
payment.

- **`#69` intended-abstention regression — synthetic-CI blind spot
  on real data.** The synthetic n=42 CI delta was green, but the
  private 100-doc real-eval lost intended abstentions on insufficient
  evidence. The eval-split discipline ([ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md))
  was already in place, but the PR-time gate was advisory. *Added
  afterward:* PR template **item 5b (real-data delta)** is now a
  required CI check
  ([`scripts/check_branch_and_issue.py --check-5b`](../scripts/check_branch_and_issue.py),
  enforced via the load-bearing path list in
  [`scripts/_governance.py`](../scripts/_governance.py)). Any PR
  touching `rag_*.py` / `ingestion.py` / `eval/` / `api/` / `docs/adr/`
  must now attach the real-data aggregate or state a behavior-no-op
  reason; the synthetic delta alone no longer clears merge.

- **Stacked-PR child auto-close on `--delete-branch` merge.** Merging
  a base branch with `gh pr merge --delete-branch` while a stacked
  dependent PR was still targeting that branch closed the dependent
  PR automatically (GitHub default behavior), losing the in-progress
  child's review state. *Added afterward:* a `PreToolUse` Bash matcher
  in [`.claude/settings.json`](../.claude/settings.json) refuses
  `gh pr merge --delete-branch` whenever
  `gh pr list --base <this-PR-head> --state open --json number` is
  non-empty. The matcher fires before the command runs, so the merge
  never reaches GitHub if a child exists. The textual rule lives in
  `CLAUDE.md > Prohibited` so it survives even if the hook is later
  disabled.

- **ADR number collisions between concurrent worktrees.** Three
  observed pairs — 0022→0023, 0023→0025, 0029→0030 — where two
  worktrees independently reserved the same ADR number from
  `ls docs/adr/`, then collided at merge. The fix is procedural
  (numbers are a shared resource, not a per-tree allocation) rather
  than a runtime gate. *Added afterward:* `CLAUDE.md > Core
  principles > "Reserve ADR numbers up front"` makes the dual check
  (`ls docs/adr/` + `gh pr list --search "ADR" --state open`)
  mandatory before drafting, and requires user confirmation on the
  proposed number to serialize the reservation across worktrees.

Each of these is a real cost paid once. New incidents that fit this
shape (governance gap → fix → no recurrence) land here.

## Onboarding shortcuts

Reading order for a new contributor:

1. [`CLAUDE.md`](../CLAUDE.md) — the rules.
2. This file — how the rules connect.
3. [`docs/adr/README.md`](./adr/README.md) and skim the 6 current
   ADRs — the load-bearing decisions.
4. [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md)
   — what the backlog comes from.

A reviewer who has 10 minutes should start at step 3.

## Hook setup

### Git hooks (opt-in, one-time per developer)

Activate:

    make install-hooks
    # or equivalently:
    git config core.hooksPath .githooks

This enables two hooks under `.githooks/`:

- **`pre-commit`** — **hard-blocks** commits that include files from the
  private side of the eval split (ADR 0005). Aligned with `.gitignore`;
  catches `git add -f` and other force-paths. Bypass with `git commit
  --no-verify` only when intentionally committing an aggregate artifact
  that the hook's allowlist missed — and fix the allowlist in the same
  change.

- **`pre-push`** — two checks:
  1. **Branch + issue convention (ADR 0007)** — **hard-fails** if the
     current branch doesn't match `<type>/issue-<N>[-<slug>]`. Mirror of
     the CI check so violations surface before push round-trip. If `gh`
     is installed and authed, also verifies issue #N exists.
  2. **Real-data eval reminder** — **soft-warns** when a push touches
     retrieval / verifier / eval / api paths, reminding you to attach
     `make real-eval-delta` to the PR (PR template item 5b). Exits 0 —
     never blocks.

  Skip both with `git push --no-verify` only with a documented reason
  (e.g. doc-only follow-up of a measured PR).

### Claude Code hook (auto-loaded, no setup)

`.claude/settings.json` is committed in this repo and auto-loaded by Claude
Code. It registers a **`PreToolUse`** hook on `Edit` / `MultiEdit` / `Write`
that prints a stderr awareness reminder when Claude is about to modify a
load-bearing file (`rag_core.py`, `ingestion.py`, `visual_ingestion.py`,
`eval/`, `api/`, `docs/adr/`). The reminder lists ADRs to consider and
notes the PR template item 5b requirement.

Hook script: [`scripts/claude-hooks/pretooluse-loadbearing.sh`](../scripts/claude-hooks/pretooluse-loadbearing.sh).
Never blocks — pure awareness layer.

### Claude Code hook (opt-in, user-global) — plan-slug race detector

When multiple concurrent worktrees run Claude Code sessions in parallel,
the harness writes plan files into a user-global directory
(`~/.claude/plans/<random-slug>.md`). The slug space is large but
collisions are not zero on 10+ concurrent worktrees (observed
2026-05-15 — issue [#779](https://github.com/hskim-solv/BidMate-DocAgent/issues/779)).

[`scripts/claude-hooks/plan-slug-race.sh`](../scripts/claude-hooks/plan-slug-race.sh)
is a **user-global** `PreToolUse` hook that blocks a `Write` to a plan
file when:

- the target file exists,
- its mtime is within the last 5 min (`PLAN_SLUG_RACE_THRESHOLD`,
  default 300 s),
- its first 200 bytes declare a different worktree slug than the
  caller's cwd-derived slug.

Convention enforced on the writer side: the first 200 chars of every
plan file should contain a marker such as
`` 본 plan은 worktree `<slug>` 의 deliverable. `` so the hook can detect
the race. Plans without a marker are not blocked (pre-convention
files / false-positive avoidance).

Override (only when you genuinely intend to overwrite another
worktree's plan): set `PLAN_SLUG_RACE_THRESHOLD=0` for the invocation.

The hook is **not** auto-registered (it lives outside the repo's
`.claude/settings.json` because the same Claude Code session may
span many repos). Wire it once in `~/.claude/settings.json`:

```jsonc
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "<absolute path to>/scripts/claude-hooks/plan-slug-race.sh"
          }
        ]
      }
    ]
  }
}
```

Regression coverage: `tests/test_plan_slug_race_hook_regression.py`.
