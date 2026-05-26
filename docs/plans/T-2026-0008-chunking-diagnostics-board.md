# Plan: T-2026-0008 Chunking Diagnostics Board

- Status: review
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0008`
- Related issue / PR: [#1514](https://github.com/hskim-solv/BidMate-DocAgent/issues/1514) / PR TBD
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-05-26

## Problem Statement

Chunking evidence is spread across Phase 2 retrieval reports, real100 corpus EDA,
and multi-chunk evidence failure aggregates. That is enough for agent workflows
but slow for human review. Reviewers need one local HTML board that shows the
chunking ablation shape, corpus chunk health, and multi-chunk evidence failure
signals without changing retrieval or chunking behavior.

## Desired Behavior

Running `scripts/render_chunking_diagnostics_board.py` writes a local
`reports/retrieval/chunking_diagnostics.html` file. The page is self-contained,
deterministic, and aggregate-only.

## Constraints

- Scope: reviewer tooling only.
- Architecture: read existing committed aggregate artifacts; do not create a new
  eval surface or runtime path.
- Compatibility: no changes to existing report files or metrics.
- Privacy: emit only aggregate metrics/counts; never render case ids, query text,
  doc ids, chunk ids, or raw text.
- Non-goals: no chunking winner claim, default change, retrieval change, verifier
  change, answer change, or eval scoring change.

## Affected Interfaces

- CLI: add `scripts/render_chunking_diagnostics_board.py`.
- Output artifacts: local ignored `reports/retrieval/chunking_diagnostics.html`.
- Tests: add focused renderer tests for aggregate metric calculation and privacy.
- Docs: mention the local board in chunking diagnostics docs.

## Data / Eval Impact

- Surface: private real-eval aggregate viewer plus existing Phase 2 retrieval
  aggregate report.
- Data boundary: aggregate-only private output under ADR 0005.
- Allowed claim: chunking diagnostics now have a local human-readable board.
- Disallowed claim: no chunking variant is promoted and no RAG quality improvement
  is claimed.
- Baseline/control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. Add a renderer that combines Phase 2 chunking aggregate files, EDA aggregate,
   and multi-chunk evidence aggregate.
2. Add HTML rendering using the shared local report shell.
3. Add tests for aggregate-only rendering and CLI output.
4. Document the local board and validation commands.

## Acceptance Criteria

- [x] Renderer emits a local self-contained HTML board.
- [x] HTML includes chunking variants, recall@10 deltas, chunk health, and
  multi-chunk retrieval outcome counts.
- [x] Tests verify private case ids are not rendered.
- [x] Existing retrieval/chunking/eval behavior is unchanged.

## Validation Strategy

Commands run:

```bash
python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py
python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py
git diff --check
```

Expected evidence:

- Focused test suite passes.
- Generated HTML is local-only and ignored by git.
- No real-eval performance or default-change claim is made.

## Rollback Strategy

Revert the renderer, tests, docs, queue entry, and this plan. Generated
`reports/retrieval/chunking_diagnostics.html` artifacts are local ignored files
and can be deleted without affecting committed evidence.

## Reviewer Notes

Attack claim wording first: the board must say the current Phase 2 chunking
ablation is diagnostic, not a winner declaration. Then inspect privacy: no
case ids, query text, doc ids, chunk ids, or raw text should render.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1514-chunking-diagnostics-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1514 / PR TBD
- Task: T-2026-0008
- Current status: implementation complete, focused validation passing.
- Files touched: scripts/render_chunking_diagnostics_board.py, tests/test_render_chunking_diagnostics_board.py, docs/retrieval/chunking-diagnostics.md, tasks/queue.md, docs/plans/T-2026-0008-chunking-diagnostics-board.md
- Decisions made: local self-contained HTML, no JS/dependencies, aggregate-only board.
- Commands run: python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py; python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py; git diff --check
- Results: pass.
- Next safe command: python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py
- Open questions: none.
- Risks: reviewer may want additional retrieval aggregate slices later; keep them separate.
```
