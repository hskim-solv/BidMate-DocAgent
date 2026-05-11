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

## Change lifecycle

The expected flow for any non-trivial change, written as a checklist
a contributor (human or AI) can walk through:

1. **Open or pick an issue.** Real-data failure taxonomy entries
   (`docs/real-data-failure-taxonomy.md`) and the prioritized backlog
   are the primary feed.
2. **Decide if it needs an ADR.** Use the criteria in
   [`docs/adr/README.md`](./adr/README.md). Most changes do **not**;
   when in doubt, ask in the issue.
3. **Inspect what exists.** Per `CLAUDE.md` ("Before coding,
   inspect..."). Name the files you read, the functions you intend
   to reuse, and what you found that surprised you.
4. **Branch + worktree if parallel.** Two independent tracks → two
   worktrees, two PRs. Coupled tracks → one PR, one branch.
5. **Make the change.** Reuse over invent. One concern per PR.
6. **Add or update tests.** Behavior change without a test is
   presumed accidental. Regressions get a guard test in
   `tests/test_*_regression.py`.
7. **Run the eval locally if relevant.** `make eval` for the public
   synthetic surface. Compare against `main`'s
   `reports/eval_summary.json` if you have it.
8. **Push, open PR.** PR body answers the pre-PR checklist in
   `CLAUDE.md` (what / files / risks / tests / eval impact / back-compat / out-of-scope).
9. **CI verifies.** `Pytest` job + `Eval delta vs base` job. The
   delta job upserts a comment with the metrics table; expect `·`
   across the board for non-RAG changes.
10. **Address review.** No mid-review scope creep — open a follow-up
    issue instead.
11. **Merge.** Squash-merge, delete the branch, remove the worktree
    if used.
12. **Update docs** if the change changed something a reviewer needs
    to know (README headline metrics, ADR status, taxonomy entry).

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
  refactor PR. *Prevented by:* ADR threshold in `CLAUDE.md`; the
  pre-PR checklist forces the question.
- Review-time scope creep — a PR grows to include "while I was
  here" fixes. *Prevented by:* "one PR, one concern" in
  `CLAUDE.md`; spawn a follow-up issue instead.

## Onboarding shortcuts

Reading order for a new contributor:

1. [`CLAUDE.md`](../CLAUDE.md) — the rules.
2. This file — how the rules connect.
3. [`docs/adr/README.md`](./adr/README.md) and skim the 5 current
   ADRs — the load-bearing decisions.
4. [`docs/portfolio-case-study.md`](./portfolio-case-study.md) — the
   narrative.
5. [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md)
   — what the backlog comes from.

A reviewer who has 10 minutes should start at step 3.
