# Plan: T-2026-0010 Priority HTML Review Boards

- Status: review
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0010`
- Related issue / PR: [#1518](https://github.com/hskim-solv/BidMate-DocAgent/issues/1518)
- Related ADR: N/A - no decision-level change
- Created: 2026-05-26
- Last updated: 2026-05-26

## Problem Statement

Several reviewer-critical aggregate surfaces exist only as JSON/Markdown
artifacts. That makes it easy for a reviewer to miss which decision surface to
inspect next, especially across private real-eval history, retrieval sweeps,
difficulty slices, verifier false negatives, parser readiness, and benchmark
claim boundaries.

## Current Behavior

Existing scripts render focused Markdown/HTML boards for some surfaces, but the
six priority surfaces are still spread across:

- `reports/real100/history/*.aggregate.json`
- `reports/retrieval/hybrid_sweep_summary.aggregate.json`
- `reports/real100/embedding_ablation_retrieval.aggregate.json`
- `reports/real100/difficulty_profile.aggregate.json`
- `reports/real100/verifier_false_negative_overlap.aggregate.json`
- `reports/private_real_eval_summary.redacted.json`
- benchmark/evaluation governance docs

## Desired Behavior

A single local script renders six self-contained HTML boards:

1. Real100 eval history timeline
2. Retrieval decision board
3. Difficulty profile board
4. Verifier / VFN overlap board
5. Parser / page citation readiness board
6. Benchmark validity board

The durable AI handoff remains Markdown (`tasks/queue.md` and this plan), while
the human review surface is HTML. If a future surface needs both, Markdown is
the canonical source-of-truth and HTML is the generated human view.

## Constraints

- Scope constraints: presentation tooling and local HTML artifacts only.
- Architecture constraints: do not change RAG runtime, parser runtime, scoring,
  or benchmark semantics.
- Compatibility constraints: missing source artifacts should degrade to empty
  tables rather than failing unrelated boards.
- Eval/privacy constraints: aggregate-only and redacted inputs; no private raw
  document or per-case payload reads.
- Tooling/CI constraints: use focused renderer tests and existing HTML helpers.
- Non-goals: no new ADR, no new eval run, no performance claim.

## Architecture Impact

- Affected modules or docs: `CLAUDE.md`,
  `scripts/render_priority_review_boards.py`, focused tests, task queue/plan
  docs.
- Affected contracts or invariants: none.
- Load-bearing paths: no runtime load-bearing path changes.
- ADR required: no, because this adds presentation artifacts only.
- Backward compatibility expectation: additive CLI only.

## Affected Interfaces

- CLI/API/config: new local script CLI with optional `--root` and `--out-dir`.
- Input data: existing aggregate JSON and Markdown docs.
- Output artifacts: local HTML files under `reports/`.
- Docs/review surfaces: task queue and plan.
- Tests/eval entrypoints: focused pytest for renderer behavior.

## Data / Eval Impact

- Surface: private real-eval aggregate, public synthetic benchmark docs, none for runtime.
- Data boundary: aggregate-only private output plus repository docs.
- Allowed claim: local reviewer visibility over existing artifacts.
- Disallowed claim: metric improvement, production readiness, or new real-eval result.
- Baseline or control affected: no.
- Benchmark/eval auditor required: no, because no scoring semantics change.

## Task Breakdown

1. Add the renderer script and six board outputs.
2. Add focused tests for escaping, output count, and path redaction behavior.
3. Generate the local HTML files and verify them through a local server.

## Acceptance Criteria

- [x] One command writes all six HTML boards.
- [x] Tests cover escaping and aggregate-only path handling.
- [x] Generated boards render locally without requiring file URL access.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 scripts/render_priority_review_boards.py
git diff --check
```

Expected evidence:

- Test/eval output: focused pytest passes.
- Generated or updated artifact: six local HTML files under `reports/`.
- Reviewer checklist or manual inspection: browser smoke via local HTTP server
  confirms all six titles, status cards, and tables load.
- Explicitly not validated, with reason: no real-eval run, because this does not
  change eval/runtime behavior.

## Rollback Strategy

Revert the script, tests, task queue entry, and plan. Generated HTML files are
local presentation artifacts and can be regenerated or removed without touching
source aggregate JSON.

## Failure Modes

- Failure mode: raw private paths or case text leaks into HTML.
- Detection signal: tests and review of source inputs; renderer reads only
  aggregate/redacted paths.
- Stop condition or fallback: stop if a desired board requires raw private cases.

## Observability

- `reports/real100/eval_history_timeline.html`
- `reports/retrieval/retrieval_decision_board.html`
- `reports/real100/difficulty_profile.html`
- `reports/real100/verifier_overlap.html`
- `reports/parser_page_citation_readiness.html`
- `reports/benchmark_validity.html`

## Reviewer Notes

Attack privacy boundary and claim wording first. The HTML boards should help
navigation only; they must not imply a fresh benchmark/eval run.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 00:00 KST

- Role: Implementer
- Branch / worktree: chore/issue-1518-priority-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Issue / PR: #1518 / TBD
- Task: T-2026-0010
- Current status: review
- Files touched: CLAUDE.md, tasks/queue.md, docs/plans/T-2026-0010-priority-html-review-boards.md, scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py
- Decisions made: Keep all six boards in one presentation-only renderer.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 scripts/render_priority_review_boards.py; git diff --check; python3 scripts/check_doc_links.py --check-all; browser smoke via http://127.0.0.1:8765
- Results: issue and branch created; focused tests, doc links, diff check, and browser smoke pass.
- Next safe command: gh pr create
- Open questions: none
- Risks: generated HTML files are local ignored artifacts; renderer and markdown source-of-truth are committed.
```
