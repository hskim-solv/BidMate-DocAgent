# Plan: T-2026-0020 v0 metric suite report

- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0020`
- Related issue / PR: [#1544](https://github.com/hskim-solv/BidMate-DocAgent/issues/1544)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0016](../adr/0016-judge-human-agreement.md), [ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md)
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

The v0 metric-suite inventory marks several families as partial, so reviewers
can see the gaps but cannot run one canonical command that reports which
families are present, partial, or missing. Numeric/date/condition exactness also
lacks a dedicated scorer.

## Current Behavior

`docs/evaluation/v0-metric-suite-inventory.md` classifies current aggregate
surfaces. `eval/run_eval.py` already emits retrieval, grounding, citation,
claim-citation, comparison, abstention, and latency aggregates, but there is no
v0 suite renderer. `eval/judges/judge_agreement.py` computes κ/ρ from a local
CSV but is not connected to a suite report.

## Desired Behavior

Add a deterministic aggregate-only v0 metric-suite renderer and a dedicated
numeric/date/condition slot exactness scorer. The report must be explicitly
non-claim-bearing and preserve ADR 0005 privacy boundaries.

## Constraints

- Scope constraints: one report surface plus the minimal scorer needed for the
  numeric/date/condition family.
- Architecture constraints: eval-only; no RAG runtime behavior change.
- Compatibility constraints: existing aggregate keys remain backward compatible.
- Eval/privacy constraints: no raw private case rows or identifiers in committed
  artifacts.
- Tooling/CI constraints: focused tests and targeted doc link checks.
- Non-goals: no RFP QA performance claim and no synthetic human labels.

## Architecture Impact

- Affected modules or docs: `eval/scorers/`, `eval/run_eval.py`,
  `scripts/run_real_eval_delta.py`, `scripts/render_v0_metric_suite_report.py`,
  `docs/evaluation/`.
- Affected contracts or invariants: ADR 0005 aggregate-only boundary, v0 metric
  suite family list.
- Load-bearing paths: `eval/`, `scripts/run_real_eval_delta.py`.
- ADR required: no; this implements ADR 0079/v0 milestones without changing
  decision policy.
- Backward compatibility expectation: older aggregate files can still render;
  new metrics show partial until regenerated.

## Affected Interfaces

- CLI/API/config: new CLI `scripts/render_v0_metric_suite_report.py`.
- Input data: aggregate JSON plus optional local judge agreement CSV.
- Output artifacts: aggregate-only JSON and Markdown report.
- Docs/review surfaces: v0 inventory and agent-gated eval loop.
- Tests/eval entrypoints: focused scorer, extractor, and renderer tests.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: metric-suite coverage/adoption status.
- Disallowed claim: RFP QA quality improved or regressed.
- Baseline or control affected: no ranking/runtime baseline change.
- Benchmark/eval auditor required: yes, for claim boundary and metric status.
- Private regeneration: `real100_v2` was regenerated locally at HEAD only to
  populate the new aggregate slot metric; the hashing index path is not
  retrieval-quality evidence.

## Task Breakdown

1. Add numeric/date/condition slot exactness scorer and aggregate wiring.
2. Add v0 metric-suite renderer with optional judge agreement CSV aggregation.
3. Update inventory/policy docs and focused tests.

## Acceptance Criteria

- [x] Numeric/date/condition metric is emitted by `score_case` and `metric_block`.
- [x] Commit-safe extractor allowlists the new metric and comparison coverage scalars.
- [x] v0 renderer reports all eight metric families without private payload leaks.
- [x] Docs distinguish implemented metric surfaces from performance claims.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_slot_metrics.py tests/test_v0_metric_suite_report.py tests/test_extract_aggregate_metadata_field_calibration.py -q
python3 -m py_compile eval/scorers/slot_metrics.py scripts/render_v0_metric_suite_report.py
python3 scripts/render_v0_metric_suite_report.py --aggregate reports/real100_v2/baseline.aggregate.json --question-distribution reports/real100_v2/question_distribution.aggregate.json --out-json reports/real100_v2/metric_suite.aggregate.json --out-md reports/real100_v2/metric_suite.md
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0020-v0-metric-suite-report.md tasks/queue.md reports/real100_v2/README.md reports/real100_v2/metric_suite.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests pass.
- Generated or updated artifact: `reports/real100_v2/metric_suite.*`.
- Reviewer checklist or manual inspection: no performance claim, no raw private
  data.
- Explicitly not validated, with reason: human/judge agreement still requires
  real `human_status` labels.

## Rollback Strategy

Revert the scorer, renderer, docs, tests, and generated aggregate/report. Do not
delete private local eval summaries, label CSVs, or raw real-eval inputs.

## Failure Modes

- Failure mode: generated report leaks raw private fields.
- Detection signal: privacy tests or `assert_public_safe` failure.
- Stop condition or fallback: stop and reduce output to aggregate scalars only.

## Observability

`reports/real100_v2/metric_suite.aggregate.json` and
`reports/real100_v2/metric_suite.md` show family statuses, metric names, and
data-dependent gaps.

## Reviewer Notes

Attack claim wording and privacy boundaries first. This PR implements measurement
surface coverage; it does not claim performance movement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 KST

- Role: Implementer
- Branch / worktree: feat/issue-1544-v0-metric-suite-report / /Users/hskim/.codex/worktrees/e622/BidMate-DocAgent
- Issue / PR: #1544 / PR #1546
- Task: T-2026-0020
- Current status: implementation complete; ready for review.
- Files touched: .gitignore, eval/scorers/slot_metrics.py, eval/scorers/__init__.py, eval/scorers/case.py, eval/run_eval.py, scripts/_utils.py, scripts/run_real_eval_delta.py, scripts/render_v0_metric_suite_report.py, docs/evaluation/v0-metric-suite-inventory.md, docs/evaluation/agent-gated-rfp-eval-loop.md, reports/real100_v2/README.md, reports/real100_v2/baseline.aggregate.json, reports/real100_v2/metric_suite.aggregate.json, reports/real100_v2/metric_suite.md, tests.
- Decisions made: no performance claim; report consumes aggregate-only inputs; numeric/date/condition is populated after private real100_v2 aggregate regeneration.
- Commands run: gh issue create; git switch -c feat/issue-1544-v0-metric-suite-report; python3 -m pytest tests/test_slot_metrics.py tests/test_v0_metric_suite_report.py tests/test_extract_aggregate_metadata_field_calibration.py -q; python3 -m py_compile eval/scorers/slot_metrics.py scripts/render_v0_metric_suite_report.py eval/scorers/case.py eval/run_eval.py scripts/run_real_eval_delta.py; python3 scripts/render_v0_metric_suite_report.py --aggregate reports/real100_v2/baseline.aggregate.json --question-distribution reports/real100_v2/question_distribution.aggregate.json --out-json reports/real100_v2/metric_suite.aggregate.json --out-md reports/real100_v2/metric_suite.md; python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0020-v0-metric-suite-report.md tasks/queue.md reports/real100_v2/README.md reports/real100_v2/metric_suite.md; git diff --check; make check-branch.
- Results: all validation commands passed; metric suite report shows 7 present, 1 partial, 0 missing after private real100_v2 aggregate regeneration.
- Next safe command: git diff --stat
- Open questions: none.
- Risks: human/judge agreement remains partial until real `human_status` labels are supplied.
```
