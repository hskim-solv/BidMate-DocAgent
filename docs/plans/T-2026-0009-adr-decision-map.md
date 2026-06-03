# Plan: T-2026-0009 ADR Decision Map

- Status: done
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0009`
- Related issue / PR: [#1516](https://github.com/hskim-solv/BidMate-DocAgent/issues/1516) / [#1517](https://github.com/hskim-solv/BidMate-DocAgent/pull/1517); refresh issue #2091
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-06-04

## Problem Statement

`docs/adr/README.md` is the source of truth for load-bearing decisions, but the
index is optimized for archival completeness rather than quick human scanning.
Reviewers need a local HTML map that shows status mix, decision areas, recent
ADRs, proposed ADRs, and superseded decisions without editing ADR content or
claiming to replace the source markdown.

## Desired Behavior

Running `scripts/render_adr_decision_map.py` writes
`reports/adr_decision_map.html`. The page is self-contained, deterministic, and
generated only from `docs/adr/README.md`.

## Constraints

- Scope: reviewer/navigation tooling only.
- Architecture: parse ADR README rows; do not edit ADR files or reserve numbers.
- Compatibility: no changes to ADR status, numbering, or README content.
- Privacy: no private data involved.
- Non-goals: no ADR creation, no status promotion, no lifecycle enforcement.

## Affected Interfaces

- CLI: add `scripts/render_adr_decision_map.py`.
- Output artifacts: local ignored `reports/adr_decision_map.html`.
- Tests: add parser/rendering/escaping tests.

## Data / Eval Impact

- Surface: none.
- Data boundary: public repository docs only.
- Allowed claim: ADR index has a local human-readable navigation board.
- Disallowed claim: HTML is not the ADR source of truth and does not change
  decision status.
- Baseline/control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. Add ADR README row parser and status/area summarizer.
2. Render local HTML using the shared report shell.
3. Add tests for canonical row parsing, status counts, and HTML escaping.
4. Record plan and queue state.

## Acceptance Criteria

- [x] Renderer emits a local self-contained HTML board.
- [x] HTML includes status mix, decision areas, recent ADRs, proposed ADRs, and
  superseded decisions.
- [x] Tests verify parser behavior and escaping.
- [x] ADR files and `docs/adr/README.md` remain unmodified.

## Validation Strategy

Commands run:

```bash
python3 scripts/render_adr_decision_map.py
python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py
python3 -m pytest -q tests/test_render_adr_decision_map.py
git diff --check
```

Expected evidence:

- Focused test suite passes.
- Generated HTML is local-only and ignored by git.
- No ADR source file changed.

## Rollback Strategy

Revert the renderer, tests, queue entry, and this plan. Generated
`reports/adr_decision_map.html` artifacts are local ignored files and can be
deleted without affecting ADR records.

## Reviewer Notes

Attack source-of-truth wording first: the HTML must not be mistaken for an ADR
registry replacement. Then inspect the row parser against README pipe-table
format and escaping of title/status text.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1516-adr-decision-map / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1516 / PR #1517
- Task: T-2026-0009
- Current status: merged in PR #1517.
- Files touched: scripts/render_adr_decision_map.py, tests/test_render_adr_decision_map.py, tasks/queue.md, docs/plans/T-2026-0009-adr-decision-map.md
- Decisions made: local self-contained HTML generated from docs/adr/README.md only.
- Commands run: python3 scripts/render_adr_decision_map.py; python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py; python3 -m pytest -q tests/test_render_adr_decision_map.py; git diff --check
- Results: pass.
- Next safe command: python3 -m pytest -q tests/test_render_adr_decision_map.py
- Open questions: none.
- Risks: keyword-based area classification is navigation-only and should not become governance logic.
```
