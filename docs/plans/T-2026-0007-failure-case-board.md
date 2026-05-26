# Plan: T-2026-0007 Failure Case Board

- Status: review
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0007`
- Related issue / PR: [#1510](https://github.com/hskim-solv/BidMate-DocAgent/issues/1510) / PR TBD
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-05-26

## Problem Statement

`scripts/render_failure_distribution.py` already emits a Markdown dashboard and
aggregate JSON, but the human-facing failure triage view is still dense. Reviewers
need a local HTML board that highlights total failures, dominant categories,
the ADR 0075 contract, refusal-axis counts, and populated slice tables without
changing classifier semantics or exposing private per-case data.

## Desired Behavior

Running the failure distribution renderer writes the existing committable
Markdown and aggregate JSON plus a local `reports/real100/failure_distribution.html`
file. The HTML is deterministic, dependency-free, and aggregate-only.

## Constraints

- Scope: reviewer tooling only.
- Architecture: reuse `build_aggregate()` and keep `eval.scorers.failure_classifier`
  as the single source of truth.
- Compatibility: keep existing Markdown and aggregate JSON paths unchanged.
- Privacy: render only counts and fail-closed enum buckets; escape HTML.
- Non-goals: no classifier, retrieval, verifier, answer, eval scoring, or private
  data changes.

## Affected Interfaces

- CLI: add `--out-html`, defaulting to `reports/real100/failure_distribution.html`;
  `--out-html ""` disables HTML output.
- Output artifacts: local ignored HTML board alongside committed Markdown/JSON.
- Tests: extend renderer tests for HTML sections, contract warning, escaping,
  disable behavior, and no private string leakage.

## Data / Eval Impact

- Surface: private real-eval aggregate viewer.
- Data boundary: aggregate-only private output under ADR 0005.
- Allowed claim: renderer now has a local human-readable failure case board.
- Disallowed claim: no model quality, retrieval, verifier, or failure-rate
  improvement claim.
- Baseline/control affected: no.
- Benchmark/eval auditor required: no.

## Task Breakdown

1. Add a small shared HTML report shell for local deterministic reports.
2. Add HTML rendering and CLI output to `scripts/render_failure_distribution.py`.
3. Add tests for HTML rendering, privacy, and disabled output.
4. Document that the failure dashboard now has a local HTML view.

## Acceptance Criteria

- [x] Renderer emits Markdown, aggregate JSON, and local HTML by default.
- [x] HTML output can be disabled with `--out-html ""`.
- [x] HTML escapes dynamic text and does not leak raw query/doc strings.
- [x] Existing Markdown/JSON behavior and schema stay unchanged.
- [x] Workflow docs mention the HTML dashboard.

## Validation Strategy

Commands run:

```bash
python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py
python3 -m pytest -q tests/test_render_failure_distribution.py
git diff --check
```

Expected evidence:

- Focused test suite passes.
- Generated HTML is local-only and ignored by git.
- No real-eval performance claim is made.

## Rollback Strategy

Revert the helper, renderer, tests, docs, queue entry, and this plan. Generated
`reports/real100/failure_distribution.html` artifacts are local ignored files
and can be deleted without affecting committed evidence.

## Reviewer Notes

Attack privacy first: HTML must not leak raw query text, answer text, doc id,
or chunk id. Then verify that `failure_distribution.md` and
`failure_distribution.aggregate.json` remain the evidence artifacts.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1510-failure-case-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1510 / PR TBD
- Task: T-2026-0007
- Current status: implementation complete, validation passing.
- Files touched: scripts/html_report.py, scripts/render_failure_distribution.py, tests/test_render_failure_distribution.py, docs/operations/failure-mode-harden-process.md, tasks/queue.md, docs/plans/T-2026-0007-failure-case-board.md
- Decisions made: local self-contained HTML, no JS/dependencies, aggregate-only report shell.
- Commands run: python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py; python3 -m pytest -q tests/test_render_failure_distribution.py; git diff --check
- Results: pass.
- Next safe command: python3 -m pytest -q tests/test_render_failure_distribution.py
- Open questions: none.
- Risks: reviewer may prefer refactoring `ai_next_actions` to the shared shell in a later PR.
```
