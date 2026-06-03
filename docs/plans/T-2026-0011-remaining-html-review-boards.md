# Plan: T-2026-0011 Remaining HTML Review Boards

- Status: done
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0011`
- Related issue / PR: [#1520](https://github.com/hskim-solv/BidMate-DocAgent/issues/1520) / [#1521](https://github.com/hskim-solv/BidMate-DocAgent/pull/1521); refresh issue [#2139](https://github.com/hskim-solv/BidMate-DocAgent/issues/2139)
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-06-04

## Problem Statement

The first priority HTML renderer covered six reviewer boards, but the remaining
candidate surfaces still require readers to jump across Markdown docs, aggregate
JSON, GitHub PR state, and governance files. That slows human review and makes
claim-boundary mistakes more likely.

## Current Behavior

`scripts/render_priority_review_boards.py` renders the first six boards:

1. Real100 eval history timeline
2. Retrieval decision board
3. Difficulty profile board
4. Verifier / VFN overlap board
5. Parser / page citation readiness board
6. Benchmark validity board

The remaining candidate surfaces exist as Markdown/JSON source artifacts but do
not have human-readable HTML boards.

## Desired Behavior

The same renderer writes fifteen total HTML boards by adding:

7. Eval surface boundary board
8. RAG pipeline EDA board
9. Rationality / judge agreement board
10. Plan / task queue board
11. Open PR merge readiness board
12. Data quality / private inventory board
13. HWP extraction comparison board
14. Governance automation board
15. Claim validator board

Markdown remains the canonical AI/source-of-truth format. HTML remains a
generated human review view.

## Constraints

- Scope constraints: presentation tooling only.
- Architecture constraints: do not change RAG runtime, parser runtime, scoring,
  or benchmark semantics.
- Compatibility constraints: existing six output paths continue to render.
- Eval/privacy constraints: use committed aggregate/redacted JSON and docs only;
  do not read private raw documents or per-case payloads.
- Tooling/CI constraints: focused tests must cover all fifteen outputs.
- Non-goals: no new eval run, no new benchmark surface, no performance claim.

## Architecture Impact

- Affected modules or docs: `scripts/render_priority_review_boards.py`, focused
  renderer tests, task queue, plan docs.
- Affected contracts or invariants: none.
- Load-bearing paths: no runtime load-bearing path changes.
- ADR required: no, because this adds generated human review views only.
- Backward compatibility expectation: additive output paths.

## Affected Interfaces

- CLI/API/config: existing renderer writes more HTML files.
- Input data: committed aggregate/redacted JSON, Markdown docs, and optional
  live `gh pr list` snapshot for open PR convenience.
- Output artifacts: local ignored HTML files under `reports/`.
- Docs/review surfaces: task queue and plan.
- Tests/eval entrypoints: focused pytest for renderer output count and escaping.

## Data / Eval Impact

- Surface: aggregate-only private real-eval, public synthetic benchmark docs,
  governance docs, and optional GitHub PR metadata.
- Data boundary: no raw private data touched.
- Allowed claim: local human reviewer visibility over existing artifacts.
- Disallowed claim: metric improvement, production readiness, or new eval result.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no, because scoring semantics do not change.

## Task Breakdown

1. Extend the renderer with the remaining nine boards.
2. Update focused tests from six outputs to fifteen outputs.
3. Generate local HTML and browser-smoke all fifteen boards.
4. Update queue/plan state.

## Acceptance Criteria

- [x] One command writes fifteen local HTML boards.
- [x] Existing six board outputs still render.
- [x] Tests cover all fifteen board titles and HTML escaping.
- [x] Browser smoke confirms all fifteen titles/cards/tables load.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 -m py_compile scripts/render_priority_review_boards.py
python3 scripts/render_priority_review_boards.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused pytest passes.
- Generated or updated artifact: fifteen local HTML files under `reports/`.
- Reviewer checklist or manual inspection: browser smoke via local HTTP server.
- Explicitly not validated, with reason: no real-eval run, because no runtime or
  scoring behavior changes.

## Rollback Strategy

Revert the renderer/test/docs changes. Generated HTML files are ignored local
artifacts and can be deleted or regenerated without touching source aggregates.

## Failure Modes

- Failure mode: HTML wording overstates existing evidence.
- Detection signal: review of titles, subtitles, and footers.
- Stop condition or fallback: stop if a board needs raw private cases.

- Failure mode: live PR snapshot is unavailable.
- Detection signal: open PR board shows fallback empty message.
- Stop condition or fallback: GitHub remains authoritative; rerun locally with
  `gh` available if a fresh PR snapshot is needed.

## Observability

- `reports/eval_surface_boundary.html`
- `reports/real100/rag_pipeline_eda.html`
- `reports/real100/rationality_judge_agreement.html`
- `reports/task_queue_board.html`
- `reports/open_pr_merge_readiness.html`
- `reports/private_data_quality_inventory.html`
- `reports/hwp_extraction_comparison.html`
- `reports/governance_automation.html`
- `reports/claim_validator.html`

Current-use boundary: any `reports/real100/*` HTML outputs above are historical
generated review views only. They are not current claim-bearing private
evidence; new task, PR, claim, and handoff decisions must use the `real100_v2`
aggregate-only surface in [Surface Map](../evaluation/surface-map.md), or
regenerate matching v2 review-board outputs before treating a board as current
evidence.

## Reviewer Notes

Attack privacy boundary, over-claiming, and whether HTML is clearly generated
from Markdown/aggregate sources. The live PR board is convenience only and must
not be treated as more authoritative than GitHub.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1520-remaining-html-boards / PR #1521
- Issue / PR: #1520 / #1521; refresh issue #2139
- Task: T-2026-0011
- Current status: merged in PR #1521; queue marks T-2026-0011 done.
- Files touched: scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py, tasks/queue.md, docs/plans/T-2026-0011-remaining-html-review-boards.md
- Decisions made: extend one renderer rather than creating a second overlapping renderer.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 -m py_compile scripts/render_priority_review_boards.py; python3 scripts/render_priority_review_boards.py; python3 scripts/check_doc_links.py --check-all; git diff --check; browser smoke via http://127.0.0.1:8765
- Results: fifteen local HTML boards generated; focused tests, py_compile, doc links, diff check, and browser smoke pass.
- Next safe command: git status --short
- Open questions: none
- Risks: generated HTML files are ignored and must be regenerated in each checkout.
```
