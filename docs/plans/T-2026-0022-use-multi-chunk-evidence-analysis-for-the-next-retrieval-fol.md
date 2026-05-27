# Plan: T-2026-0022 Use multi-chunk evidence analysis for the next retrieval follow-up

- Status: review
- Owner role: Planner -> Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0022`
- Related issue / PR: [#1563](https://github.com/hskim-solv/BidMate-DocAgent/issues/1563) / PR TBD
- Source brief: `reports/agent_loop/codex_tasks/001-multi-chunk-follow-up.md`
- Suggested final path: `docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`

## Problem

multi-chunk aggregate is available: 97/99 top-10 failures; 97 limited-depth cases.
The current strategy source is the older `reports/real100/` aggregate with source
SHA-256 prefix `714c08f9996d`; it is not a fresh `real100_v2` multi-chunk
measurement.

## Desired Outcome

Turn the aggregate multi-chunk evidence split into one scoped measurement
follow-up, while preventing a stale aggregate from being mistaken for current
`real100_v2` retrieval evidence.

## Scope

- Convert the planner brief into one narrow, reviewable Codex task.
- Render a public-safe strategy decision from the existing aggregate.
- Record the current `real100_v2` freshness check: 100 parsed Markdown exports
  exist, but the current `real100_v2` index has 0% chunk page metadata coverage.
- Reuse existing BidMate operating docs, queue, plans, validation commands, and reviewer prompts.
- Keep generated artifacts aggregate-only and public-safe.

## Out of Scope

- Auto-merge, auto-push, PR creation/close/merge, branch deletion, or force-push.
- Benchmark, performance, private real-eval, or architecture tradeoff decisions without ADR 0079 agent-gate evidence.
- Raw private question, answer, evidence, doc_id, chunk_id, filenames, or exact local paths.
- Retrieval, reranker, chunking, prompt, verifier, or answer runtime changes.

## Surface / Claim Boundary

- Initial classification: `next_experiment_candidate`
- Workset: `general`
- Source PRs: `PR corpus`
- Lane: `parallel-safe`
- Eval surface: classify again after implementation if changed files touch eval, benchmark, metrics, reports, configs, or claims.
- Disallowed claim: do not claim product quality, benchmark lift, or private real-eval success from this draft alone.

## Freshness Check

- `data/private/real100_v2/parsed_md` exists locally with 100 Markdown files
  plus `export_manifest.local.json` listing 100 documents.
- `data/private/real100_v2/converted_pdfs` exists locally with 94 converted
  PDFs; raw filenames and paths stay private.
- `data/index/real100_v2/index.json` reports `text_source=pdf_pymupdf4llm` for
  21,800 chunks, but `scripts/page_metadata_recovery_audit.py` reports 0.0
  coverage for chunk page metadata, `page_span`, and `regions.page_number`.
- The `real100_v2` index embedding is currently `hashing` /
  `local-hashing-bow`, so it is not MiniLM semantic evidence.

Conclusion: the Markdown conversion exists, but page-aware retrieval evidence
still requires a page-aware re-index before making a concrete multi-chunk
retrieval change.

## Implementation Steps

1. Read the required operating docs and this plan.
2. Inspect the cited workflow surface and existing tests.
3. Render the aggregate-only strategy decision.
4. Add focused tests for strategy provenance/freshness wording.
5. Run focused validation and `git diff --check`.
6. Leave a handoff with required fields and reviewer focus.

## Validation

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py
python3 scripts/render_multi_chunk_retrieval_strategy.py
export REAL_EVAL_ROOT=/path/to/private/BidMate-DocAgent
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_v2" --format markdown
git diff --check
```

## Reviewer Focus

- Scope control against the source brief.
- Completion proof: Focused validation passes and the follow-up evidence is recorded.
- Privacy boundary and claim wording.
- Freshness boundary: no claim that the older `real100/` strategy report is a
  current `real100_v2` result.
- Conservative eval surface classification.
- Validation evidence matches commands actually run.

## Session Handoff

- Role: Planner -> Implementer
- Lifecycle stage: implementation
- Branch / worktree: eval/issue-1563-multi-chunk-followup-implementation / Codex worktree
- Task: T-2026-0022
- Current status: aggregate-only strategy decision implemented; concrete retrieval
  change deferred until page-aware re-index evidence exists.
- Files touched: .githooks/pre-commit, scripts/render_multi_chunk_retrieval_strategy.py, tests/test_render_multi_chunk_retrieval_strategy.py, docs/evaluation/multi_chunk_retrieval_strategy.md, reports/real100/multi_chunk_retrieval_strategy.aggregate.json, docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md, tasks/queue.md
- Commands run: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py; python3 scripts/render_multi_chunk_retrieval_strategy.py; export REAL_EVAL_ROOT=/path/to/private/BidMate-DocAgent; python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_v2" --format markdown; python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md docs/evaluation/multi_chunk_retrieval_strategy.md tasks/queue.md; bash -n .githooks/pre-commit; git diff --check; make check-branch
- Results: strategy recommendation is `defer_until_page_metadata_recovery`; `real100_v2` has 100 parsed Markdown exports but current index page metadata coverage is 0.0.
- Validation evidence: focused tests, doc-link check, whitespace check, branch check, and page metadata recovery audit completed.
- Blockers: concrete retrieval implementation is blocked on page-aware re-index evidence, not on missing Markdown conversion.
- Open risks: `real100_v2` parsed Markdown exists but lacks structured page metadata in the current index; MiniLM semantic baseline evidence is also absent from this task.
- Next action: review this aggregate-only no-go decision, then run page-aware re-index / MiniLM baseline follow-ups separately (#1573, #1575).
- Next safe command: python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py
- Reviewer focus: source freshness, privacy-safe aggregate-only wording, and no RAG performance claim.
- Eval surface: report/measurement decision only; no retrieval, reranker, verifier, prompt, answer, or eval runtime behavior change.
