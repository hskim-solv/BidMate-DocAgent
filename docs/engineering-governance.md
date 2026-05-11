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
| Load-bearing decisions | [`docs/adr/`](./adr/README.md) | One short file per decision; status-tracked. |
| Behavior contracts | [ADR 0003](./adr/0003-structured-answer-citation-contract.md), [`docs/answer-policy.md`](./answer-policy.md) | Answer JSON shape, `schema_version`, status values. |
| Eval surfaces | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`eval/config.yaml`](../eval/config.yaml), `eval/*.example.yaml` | Public synthetic is committed; private local is `.gitignore`d. |
| Reviewer-facing metrics | `reports/eval_summary.json`, README headline table | The PR eval delta workflow upserts a PR comment with the diff. |
| Failure analysis | [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md), [`docs/failure-cases.md`](./failure-cases.md) | Drives the prioritized backlog. |
| API demo | [`docs/api-demo.md`](./api-demo.md), `api/main.py` | Reviewer playground; never the source of truth for measurement. |
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
   `feat/issue-79-senior-positioning`. Claude Code's default
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
| `real-data-evaluation` | Private 100-doc real-data eval health: failures observed in [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md), Korean-specific axes, abstention regressions. | `eval`, `fix` that lands a measurable real-data delta. |

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

## Onboarding shortcuts

Reading order for a new contributor:

1. [`CLAUDE.md`](../CLAUDE.md) — the rules.
2. This file — how the rules connect.
3. [`docs/adr/README.md`](./adr/README.md) and skim the 6 current
   ADRs — the load-bearing decisions.
4. [`docs/portfolio-case-study.md`](./portfolio-case-study.md) — the
   narrative.
5. [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md)
   — what the backlog comes from.

A reviewer who has 10 minutes should start at step 3. A reviewer
evaluating senior-engineering signals (architectural reasoning,
measurement rigor, governance, regression discipline) should read
[`docs/senior-positioning.md`](./senior-positioning.md) first — it
threads the artifacts above into one interview-ready narrative
without duplicating their content.

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
