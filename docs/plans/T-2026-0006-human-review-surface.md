# Plan: T-2026-0006 Human Review Surface

- Status: done
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0006`
- Related issue / PR: [#1506](https://github.com/hskim-solv/BidMate-DocAgent/issues/1506) / [#1509](https://github.com/hskim-solv/BidMate-DocAgent/pull/1509); refresh issue #2089
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-06-04

## Problem Statement

`scripts/ai_next_actions.py` already turns PR/readiness/eval aggregate state into
deterministic Markdown, but that output is still optimized for agents and task
handoff. Human reviewers need a compact current-state page that surfaces the
top task, blockers, private delta need, page-citation gate, and privacy guard
without changing the planner's source-of-truth logic.

## Desired Behavior

Running the planner writes the existing Markdown task brief plus a local
`reports/ai_next_actions.html` file. The HTML is self-contained, deterministic,
and explicitly local-only; it is a status board, not PR evidence.

## Constraints

- Scope: workflow/reviewer tooling only.
- Architecture: reuse the existing `WorkItem` and `SourceState` model.
- Compatibility: keep existing Markdown and `reports/codex_tasks/*.md` outputs.
- Privacy: render only existing aggregate/redacted strings and escape HTML.
- Non-goals: no retrieval, verifier, answer, eval, private-data, or external API changes.

## Affected Interfaces

- CLI: add `--out-html`, defaulting to `reports/ai_next_actions.html`; `--out-html ""` disables HTML output.
- Output artifacts: add local ignored `reports/ai_next_actions.html`.
- Docs/review surfaces: document the HTML status board in workflow and review docs.

## Data / Eval Impact

- Surface: none.
- Data boundary: aggregate-only or redacted local artifacts already accepted by the planner.
- Allowed claim: planner now has a human-readable local status board.
- Disallowed claim: the HTML is not eval evidence and does not prove performance or readiness.
- Baseline/control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. Add stdlib-only HTML rendering to `scripts/ai_next_actions.py`.
2. Extend planner tests for determinism, privacy, escaping, gitignore coverage, and disabled HTML output.
3. Update docs so reviewers know when to use the HTML and when to verify source evidence.

## Acceptance Criteria

- [x] Planner emits Markdown, task briefs, and self-contained HTML from the same work items.
- [x] HTML escapes PR/user-provided text.
- [x] Forbidden private readiness fields do not appear in generated Markdown, HTML, or task briefs.
- [x] `--out-html ""` skips HTML generation.
- [x] Review docs state that HTML is local status, not approval evidence.

## Validation Strategy

Commands run:

```bash
python3 -m py_compile scripts/ai_next_actions.py
python3 -m pytest -q tests/test_ai_next_actions.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

Expected evidence:

- Focused test suite passes.
- Documentation links pass.
- Browser visual check was attempted but `file://` navigation was blocked by the app URL policy; no browser workaround used.

## Rollback Strategy

Revert the script, tests, docs, queue entry, and this plan. Generated
`reports/ai_next_actions.html` artifacts are ignored local files and can be
deleted without affecting committed evidence.

## Reviewer Notes

Attack privacy-safe rendering first: HTML must not leak raw readiness fields or
execute PR/user-provided text. Then verify output compatibility and no evidence
over-claim.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1506-human-review-surface / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1506 / PR #1509
- Task: T-2026-0006
- Current status: merged in PR #1509.
- Files touched: scripts/ai_next_actions.py, tests/test_ai_next_actions.py, docs/operations/ai-codex-workflow.md, docs/reviews/README.md, tasks/queue.md, docs/plans/T-2026-0006-human-review-surface.md
- Decisions made: local self-contained HTML, no JS/dependencies, non-evidence status board.
- Commands run: python3 -m py_compile scripts/ai_next_actions.py; python3 -m pytest -q tests/test_ai_next_actions.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch
- Results: pass; browser file:// visual check blocked by app policy.
- Next safe command: python3 -m pytest -q tests/test_ai_next_actions.py
- Open questions: none.
- Risks: reviewer may prefer moving inline CSS to a separate committed template later.
```
