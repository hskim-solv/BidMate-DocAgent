# Plan: T-2026-0017 v0-b offline/online run manifest

- Status: review
- Owner role: Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0017`
- Related issue / PR: [#1542](https://github.com/hskim-solv/BidMate-DocAgent/issues/1542) / N/A
- Related ADR: [ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md)
- Created: 2026-05-27
- Last updated: 2026-05-27

## Problem Statement

ADR 0079 defines v0 as producing metric-suite aggregates across offline and
online environments, but current run manifests do not consistently record the
offline/online execution axis, provider/model provenance, payload class, and
private-data egress mode.

Without this, later metric reports can compare numbers without enough context to
review privacy boundary or environment compatibility.

## Current Behavior

`eval/run_eval.py::compute_run_manifest` records git/config/index/chunking
provenance. `scripts/agent_loop.py manifest` records generated artifact
freshness. Neither one separately automates the ADR 0079 offline/online
execution environment contract.

## Desired Behavior

`eval/run_eval.py` records the v0-b offline/online environment block inside
`run_manifest`, and `scripts/agent_loop.py eval-run-manifest` can write a
standalone privacy-safe manifest artifact for review and handoff.

## Constraints

- Scope constraints: additive manifest fields only.
- Architecture constraints: do not change RAG runtime, scoring, ranking, or eval
  metric formulas.
- Compatibility constraints: existing `run_manifest` keys remain present.
- Eval/privacy constraints: aggregate/provenance only; no raw private content or
  exact local paths.
- Tooling/CI constraints: keep tests deterministic and offline.
- Non-goals: do not run private real-eval and do not make a performance claim.

## Architecture Impact

- Affected modules or docs: `eval/run_eval.py`, `scripts/agent_loop.py`,
  `scripts/run_real_eval_delta.py`, tests, eval docs, queue.
- Affected contracts or invariants: `run_manifest` gains additive sections;
  real-eval aggregate extraction whitelists those sections.
- Load-bearing paths: `eval/run_eval.py`, `scripts/run_real_eval_delta.py`.
- ADR required: no; implements accepted ADR 0079 milestone.
- Backward compatibility expectation: existing consumers can ignore the new
  nested sections.

## Affected Interfaces

- CLI/API/config: new `scripts/agent_loop.py eval-run-manifest`; optional
  `run_environment` config block and env overrides for eval runs.
- Input data: no private raw data read beyond hashing existing config files.
- Output artifacts: `reports/agent_loop/offline_online_run_manifest.json` and
  additive `run_manifest` sections.
- Docs/review surfaces: v0-b schema doc and milestone links.
- Tests/eval entrypoints: focused unit tests for manifest schema and privacy.

## Data / Eval Impact

- Surface: private real-eval provenance / eval harness plumbing.
- Data boundary: aggregate-only private output; no data touched.
- Allowed claim: manifest/provenance automation works.
- Disallowed claim: no benchmark, metric, regression, or RFP quality claim.
- Baseline or control affected: no; scoring and retrieval behavior unchanged.
- Benchmark/eval auditor required: yes, because manifest fields are eval
  provenance.

## Task Breakdown

1. Add run-environment provenance to `compute_run_manifest`.
2. Add a standalone `eval-run-manifest` CLI for handoff/report artifacts.
3. Whitelist the new scalar manifest sections in real-eval aggregate extraction.
4. Add focused schema and privacy tests.
5. Update v0-b docs and queue state.

## Acceptance Criteria

- [x] Offline and online manifest examples share the same section schema.
- [x] Offline manifests force `private_data_egress=none`.
- [x] Online manifests record provider/model/payload class/egress mode.
- [x] Config paths are not serialized in committed manifest fields.
- [x] Privacy tests cover raw private text and exact local path redaction.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_agent_loop.py tests/test_run_manifest_versioning_regression.py tests/test_eval_metrics.py tests/test_run_real_eval_delta.py -q
python3 -m py_compile scripts/agent_loop.py eval/run_eval.py scripts/run_real_eval_delta.py
python3 scripts/agent_loop.py eval-run-manifest --mode offline --payload-class none --egress-mode none --provider local --model local-judge-v1 --judge-backend local-llm
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/offline-online-run-manifest.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md tasks/queue.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused pytest and py_compile pass.
- Generated or updated artifact: local `reports/agent_loop/offline_online_run_manifest.json`.
- Reviewer checklist or manual inspection: no raw private content and no
  performance claim.
- Explicitly not validated, with reason: private real-eval not run; this is
  manifest plumbing only.

## Rollback Strategy

Revert the PR. Do not delete local private eval outputs or ignored real-eval
artifacts during rollback.

## Failure Modes

- Failure mode: online manifests omit provider/model.
- Detection signal: `eval-run-manifest` validation raises `ValueError`.
- Stop condition or fallback: keep the PR draft and fix schema input handling.

- Failure mode: committed aggregate extraction leaks path-like manifest fields.
- Detection signal: `tests/test_run_real_eval_delta.py` privacy assertions fail.
- Stop condition or fallback: tighten the whitelist.

## Observability

- `run_manifest.environment`, `run_manifest.model`, `run_manifest.payload`, and
  `run_manifest.privacy` in eval summaries.
- `reports/agent_loop/offline_online_run_manifest.json` for standalone handoff.
- Focused pytest coverage.

## Reviewer Notes

Attack privacy boundary, schema compatibility, and claim wording first. This PR
must not be reviewed as a performance or metric improvement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-27 KST

- Role: Maintainer
- Branch / worktree: chore/issue-1542-offline-online-manifest / /Users/hskim/.codex/worktrees/1542/BidMate-DocAgent
- Task: T-2026-0017
- Issue / PR: #1542 / N/A
- Current status: implementation validated; ready for PR review
- Files touched: eval/run_eval.py, scripts/agent_loop.py, scripts/run_real_eval_delta.py, docs/evaluation/offline-online-run-manifest.md, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/evaluation/v0-metric-suite-inventory.md, docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md, tasks/queue.md, tests/test_agent_loop.py, tests/test_eval_metrics.py, tests/test_run_manifest_versioning_regression.py, tests/test_run_real_eval_delta.py
- Commands run: python3 -m pytest tests/test_agent_loop.py tests/test_run_manifest_versioning_regression.py tests/test_eval_metrics.py tests/test_run_real_eval_delta.py -q; python3 -m py_compile scripts/agent_loop.py eval/run_eval.py scripts/run_real_eval_delta.py; python3 scripts/agent_loop.py eval-run-manifest --mode offline --payload-class none --egress-mode none --provider local --model local-judge-v1 --judge-backend local-llm; python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/offline-online-run-manifest.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md tasks/queue.md; git diff --check; make check-branch; python3 scripts/_governance.py --check-eval-privacy
- Results: passed
- Validation evidence: focused pytest, py_compile, manifest CLI smoke, targeted doc link check, diff whitespace check, branch/issue check, eval privacy check
- Blockers: none known
- Open risks: review nested manifest whitelist and no-claim wording
- Next action: run focused validation
- Next safe command: python3 -m pytest tests/test_agent_loop.py tests/test_run_manifest_versioning_regression.py tests/test_eval_metrics.py tests/test_run_real_eval_delta.py -q
- Reviewer focus: privacy-safe scalar whitelist, backward-compatible manifest fields, no performance claim
- Eval surface: provenance plumbing only; no private real-eval run
```
