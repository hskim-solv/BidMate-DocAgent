# Plan: T-2026-0012 Extended HTML Review Boards

- Status: review
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0012`
- Related issue / PR: [#1522](https://github.com/hskim-solv/BidMate-DocAgent/issues/1522)
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-05-26

## Problem Statement

The local HTML renderer covers the core reviewer boards, but several
second-pass reviewer and portfolio surfaces still require reading Markdown and
aggregate JSON directly. These are useful for external review, evaluation
validity, and governance explanation.

## Current Behavior

`scripts/render_priority_review_boards.py` writes fifteen local HTML boards.
Additional source artifacts exist for review checklist routing, cost frontier,
embedding model decisions, distinguishing power, variance, failure slices,
multi-chunk evidence, public synthetic benchmark inventory, architecture maps,
portfolio explanation, and governance incidents.

## Desired Behavior

The same renderer writes twenty-five total HTML boards by adding:

1. Review checklist selector board
2. Cost frontier board
3. Embedding model decision board
4. Distinguishing power / variance board
5. Failure slices deep dive board
6. Multi-chunk evidence board
7. Public synthetic benchmark board
8. Architecture / module map board
9. Portfolio / external reviewer board
10. Governance incidents board

Markdown remains the canonical AI/source-of-truth format. HTML remains a
generated human review view.

## Constraints

- Scope constraints: presentation tooling only.
- Architecture constraints: do not change runtime code, parser behavior,
  scoring, or benchmark semantics.
- Compatibility constraints: existing fifteen output paths continue to render.
- Eval/privacy constraints: use committed aggregate/redacted JSON and docs only.
- Tooling/CI constraints: focused tests must cover all twenty-five outputs.
- Non-goals: no new eval run, no new benchmark surface, no ADR, no performance
  claim.

## Architecture Impact

- Affected modules or docs: `scripts/render_priority_review_boards.py`, focused
  renderer tests, task queue, plan docs.
- Affected contracts or invariants: none.
- Load-bearing paths: no runtime load-bearing path changes.
- ADR required: no, because this adds generated human review views only.
- Backward compatibility expectation: additive output paths.

## Affected Interfaces

- CLI/API/config: existing renderer writes more local HTML files.
- Input data: committed aggregate/redacted JSON and Markdown docs.
- Output artifacts: local ignored HTML files under `reports/`.
- Docs/review surfaces: task queue and plan.
- Tests/eval entrypoints: focused pytest for renderer output count and escaping.

## Data / Eval Impact

- Surface: aggregate-only private real-eval, public synthetic benchmark docs,
  governance docs, portfolio docs.
- Data boundary: no raw private data touched.
- Allowed claim: local human reviewer visibility over existing artifacts.
- Disallowed claim: metric improvement, production readiness, or new eval result.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no, because scoring semantics do not change.

## Task Breakdown

1. Extend the renderer with ten second-pass boards.
2. Update focused tests from fifteen outputs to twenty-five outputs.
3. Generate local HTML and browser-smoke all twenty-five boards.
4. Update queue/plan state.

## Acceptance Criteria

- [x] One command writes twenty-five local HTML boards.
- [x] Existing fifteen board outputs still render.
- [x] Tests cover all twenty-five board titles and HTML escaping.
- [x] Browser smoke confirms all twenty-five titles/cards/tables load.

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
- Generated or updated artifact: twenty-five local HTML files under `reports/`.
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

- Failure mode: portfolio/external-review board invents claims.
- Detection signal: board text must point to existing docs rather than adding
  new metric claims.
- Stop condition or fallback: remove claim-like wording and keep it as a route
  map only.

## Observability

- `reports/review_checklist_selector.html`
- `reports/cost_frontier.html`
- `reports/embedding_model_decision.html`
- `reports/real100/distinguishing_variance.html`
- `reports/real100/failure_slices_deep_dive.html`
- `reports/real100/multi_chunk_evidence.html`
- `reports/public_synthetic_benchmark.html`
- `reports/architecture_module_map.html`
- `reports/portfolio_external_reviewer.html`
- `reports/governance_incidents.html`

Current-use boundary: any `reports/real100/*` HTML outputs above are historical
generated review views only. They are not current claim-bearing private
evidence; new task, PR, claim, and handoff decisions must use the `real100_v2`
aggregate-only surface in [Surface Map](../evaluation/surface-map.md), or
regenerate matching v2 extended-board outputs before treating a board as current
evidence.

## Reviewer Notes

Attack privacy boundary, over-claiming, and whether the boards are clearly
generated views over Markdown/aggregate sources. These boards should improve
navigation, not introduce a new measurement surface.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1522-extended-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1522 / TBD
- Task: T-2026-0012
- Current status: implemented and validated; PR pending.
- Files touched: scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py, tasks/queue.md, docs/plans/T-2026-0012-extended-html-review-boards.md
- Decisions made: extend the existing renderer to twenty-five boards.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 -m py_compile scripts/render_priority_review_boards.py; python3 scripts/render_priority_review_boards.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch; browser smoke via http://127.0.0.1:8765
- Results: twenty-five local HTML boards generated; focused tests, py_compile, doc links, diff check, branch check, and browser smoke pass.
- Next safe command: gh pr create
- Open questions: none
- Risks: generated HTML files are ignored and must be regenerated in each checkout.
```
