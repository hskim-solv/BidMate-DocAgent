# Plan: T-2026-0015 v0 metric suite inventory

- Status: done
- Owner role: Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0015`
- Related issue / PR: Issue #1535 / PR #1536
- Related ADR: ADR 0079; ADR 0005; ADR 0016
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

ADR 0079 and the agent-gated eval-loop policy define a v0-a milestone to
inventory which metric families already exist in private real-eval aggregate
surfaces. Without that inventory, the next metric-suite PRs can blur present
metrics, partial proxies, and missing measurement work.

## Current Behavior

`docs/evaluation/agent-gated-rfp-eval-loop.md` lists the metric families and
v0/v1/v2 milestones, but it does not classify current aggregate artifacts.
Committed private real-eval aggregate files exist under `reports/real100/` and
`reports/real100_v2/`, while raw private eval summaries and per-case rows remain
local-only.

## Desired Behavior

The repo should have an aggregate-only v0-a inventory that classifies every
metric family as present, partial, or missing, names the current source
artifacts, and makes the follow-up work visible without making a performance
claim.

## Constraints

- Scope constraints: docs and queue only.
- Architecture constraints: no runtime, scorer, or eval runner behavior change.
- Compatibility constraints: no command or schema rename.
- Eval/privacy constraints: no private real-eval run; no raw private content; no performance claim.
- Tooling/CI constraints: focused doc link and whitespace validation.
- Non-goals: no metric implementation, no v0-c report shell, no private-data egress.

## Architecture Impact

- Affected modules or docs: `docs/evaluation/v0-metric-suite-inventory.md`,
  `docs/evaluation/agent-gated-rfp-eval-loop.md`, `docs/plans/`, `tasks/queue.md`.
- Affected contracts or invariants: none.
- Load-bearing paths: none.
- ADR required: no; this implements an ADR 0079 milestone without a new decision.
- Backward compatibility expectation: existing eval artifacts and commands remain unchanged.

## Affected Interfaces

- CLI/API/config: none.
- Input data: committed aggregate-only report artifacts.
- Output artifacts: `docs/evaluation/v0-metric-suite-inventory.md`.
- Docs/review surfaces: agent-gated eval-loop next milestones and task queue.
- Tests/eval entrypoints: doc link check and diff whitespace check.

## Data / Eval Impact

- Surface: private real-eval aggregate inventory.
- Data boundary: aggregate-only private output.
- Allowed claim: v0-a inventory classifies current metric-family coverage.
- Disallowed claim: no RFP QA quality, benchmark, private real-eval, or performance improvement claim.
- Baseline or control affected: no, with reason: this is documentation only.
- Benchmark/eval auditor required: yes, for metric-family classification and claim boundary.

## Task Breakdown

1. Add a v0 metric-suite inventory document.
2. Link the v0-a milestone to that inventory from the agent-gated eval-loop policy.
3. Add queue state and handoff evidence for issue #1535.
4. Validate links, branch naming, and diff whitespace.

## Acceptance Criteria

- [x] Inventory covers retrieval, grounding, citation precision, claim-citation alignment, comparison coverage, abstention calibration, numeric/date/condition accuracy, and human/judge agreement.
- [x] Each family is classified as present, partial, or missing with aggregate-only source paths.
- [x] The document explicitly says it is not a performance claim and does not expose raw private content.
- [x] Queue and plan link the work to issue #1535 and the v0-a milestone.

## Validation Strategy

Commands that must be run:

```bash
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0015-v0-metric-suite-inventory.md tasks/queue.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: targeted doc link check passes.
- Generated or updated artifact: v0 inventory doc.
- Reviewer checklist or manual inspection: no raw private identifiers or performance wording.
- Explicitly not validated: private real-eval, because this change makes no metric claim.

## Rollback Strategy

Revert the docs and queue changes in one PR. Do not delete existing aggregate
reports; this PR only references them.

## Failure Modes

- Failure mode: inventory wording implies quality improvement.
- Detection signal: reviewer finds performance-claim language without private real-eval delta.
- Stop condition or fallback: replace claim wording with coverage-only language.

## Observability

- `docs/evaluation/v0-metric-suite-inventory.md`
- `python3 scripts/check_doc_links.py --check-all --paths ...`
- `git diff --check`
- `make check-branch`

## Reviewer Notes

Attack the classification boundaries first: partial families should not be
described as adopted metrics. Then check privacy wording and ensure the PR body
does not claim performance movement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 KST

- Role: Maintainer
- Branch / worktree: docs/issue-1535-v0-metric-inventory / /Users/hskim/.codex/worktrees/43e3/BidMate-DocAgent
- Issue / PR: #1535 / PR #1536
- Task: T-2026-0015
- Current status: merged in PR #1536.
- Files touched: docs/evaluation/v0-metric-suite-inventory.md, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/plans/T-2026-0015-v0-metric-suite-inventory.md, tasks/queue.md
- Decisions made: classify grounding, comparison coverage, abstention calibration, numeric/date/condition, and human/judge agreement as partial where current artifacts expose only a narrower metric, null field, labels, or tooling rather than full canonical coverage.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0015-v0-metric-suite-inventory.md tasks/queue.md; git diff --check; make check-branch
- Results: passed
- Next safe command: git diff --stat
- Open questions: none
- Risks: reviewer should confirm partial/present boundaries and no-performance-claim wording.
```
