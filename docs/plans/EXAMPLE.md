# Plan: T-2026-0002 Evaluation Regression Safety for Claim-Bearing Runs

- Status: proposed
- Owner role: Evaluation Systems Designer
- Related task: `tasks/queue.md::T-2026-0002` (example)
- Related issue / PR: example only
- Related ADR: `docs/adr/0005-eval-split-public-synthetic-private-local.md`, `docs/adr/0055-claim-validator-as-pr-gate.md`
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

Claim-bearing evaluation work can regress quietly when a PR updates metrics,
gold data, or report wording without preserving the baseline/control surface.
The reviewer then has to rediscover which claims are supported by smoke tests,
synthetic benchmarks, or private real-eval aggregates.

## Current Behavior

The repository separates public fixture smoke, public synthetic benchmark, and
private real-eval surfaces. Claim validation exists for explicit PR-body metric
claims, and ADRs define the public/private boundary. However, an AI session that
joins midstream can still miss which commands produced the evidence, which
artifact is allowed to support the claim, and which wording is disallowed.

## Desired Behavior

Every claim-bearing eval change should leave a compact execution trail: the
surface, allowed claim, control or baseline, commands, artifacts, and reviewer
attack points are visible before implementation and updated at handoff.

## Constraints

- Scope constraints: focus on documentation and process wiring; do not change
  scoring code in this plan.
- Architecture constraints: preserve existing answer contract and eval preset
  names.
- Compatibility constraints: existing CI and local eval commands continue to
  work.
- Eval/privacy constraints: private RFP data stays local; only aggregate
  private results may be referenced.
- Tooling/CI constraints: command examples must be runnable from repo root.
- Non-goals: do not introduce a new metric, benchmark, or judge.

## Architecture Impact

- Affected modules or docs: eval operating docs, PR template wording, plan docs.
- Affected contracts or invariants: claim-bearing evidence must identify its
  eval surface and control.
- Load-bearing paths: none unless eval config or scorer code changes in a
  follow-up.
- ADR required: no for process clarification; yes if a new claim gate or eval
  surface is introduced.
- Backward compatibility expectation: existing reports and PRs remain valid.

## Affected Interfaces

- CLI/API/config: no runtime interface change.
- Input data: no new data input.
- Output artifacts: evaluation summaries and validation reports are referenced,
  not reformatted.
- Docs/review surfaces: plan docs and reviewer notes.
- Tests/eval entrypoints: existing smoke and eval commands only.

## Data / Eval Impact

- Surface: private real-eval for claim-bearing aggregate evidence; public
  fixture smoke for reproducible sanity checks.
- Data boundary: aggregate-only private output.
- Allowed claim: "This change preserves or improves the measured aggregate on
  the named eval surface under the listed command."
- Disallowed claim: "This proves general real-world RFP quality" without the
  private real-eval evidence and claim gate.
- Baseline or control affected: no; any control change requires a separate ADR.
- Benchmark/eval auditor required: yes for metric or claim wording changes.

## Task Breakdown

1. Identify the eval surface and existing control or baseline for the work.
2. Record the exact command, config, index provenance, and expected output
   artifact in the plan.
3. Update docs or PR wording so allowed and disallowed claims are explicit.
4. Run the lightweight validation commands and attach aggregate evidence.
5. Add a handoff note with the next safe command and remaining reviewer risks.

## Acceptance Criteria

- [ ] The plan names the eval surface and disallowed claim before implementation.
- [ ] The validation command and expected artifact path are reproducible from the
  repo root.
- [ ] Reviewer notes identify the first claim or data-boundary risk to attack.
- [ ] Handoff notes are sufficient for a new session to resume without reading
  the entire eval history.

## Validation Strategy

Commands that must be run:

```bash
test -f docs/evaluation/surface-map.md
test -f docs/adr/0055-claim-validator-as-pr-gate.md
python3 scripts/check_doc_links.py --check-all
```

Expected evidence:

- Test/eval output: doc-link check exits successfully.
- Generated or updated artifact: N/A - this plan changes process docs only.
- Reviewer checklist or manual inspection: reviewer confirms claim wording maps
  to exactly one eval surface.
- Explicitly not validated, with reason: private real-eval is not run for this
  process-only example.

## Rollback Strategy

Revert the documentation or PR wording changes. Do not delete historical eval
reports, ADRs, or private aggregate artifacts; they are evidence records, not
temporary build output.

## Failure Modes

- Failure mode: public fixture smoke result is described as real-eval evidence.
- Detection signal: reviewer cannot map the claim to a surface in
  `docs/evaluation/surface-map.md`.
- Stop condition or fallback: stop claim publication and rewrite the claim as a
  smoke-only sanity result.

## Observability

- Plan fields: `Data / Eval Impact`, `Validation Strategy`, and `Reviewer Notes`.
- PR evidence: command output, aggregate report path, and claim validator result.
- Review artifact: selected eval/benchmark checklist and unresolved objections.

## Reviewer Notes

Attack claim wording first. Then verify that the named command, config, and
artifact support the exact claim and do not imply a broader real-world result.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-25 15:30 KST

- Role: Evaluation Systems Designer
- Branch / worktree: example only
- Issue / PR: N/A
- Task: T-2026-0002
- Current status: example plan complete
- Files touched: docs/plans/EXAMPLE.md
- Decisions made: no new eval surface; use existing claim boundary
- Commands run: not run for example
- Results: N/A
- Next safe command: python3 scripts/check_doc_links.py --check-all
- Open questions: whether a future PR should add CI enforcement
- Risks: process docs can be ignored unless PR reviewers require them
```
