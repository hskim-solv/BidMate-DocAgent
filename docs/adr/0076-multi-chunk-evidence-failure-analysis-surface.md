# 0076: Multi-chunk evidence failure analysis surface

- **Status**: accepted
- **Date**: 2026-05-25
- **Deciders**: hskim (solo author)
- **Related**: ADR 0001, ADR 0003, ADR 0005, ADR 0069, ADR 0075

## Context

Real-eval failure analysis already has aggregate-only failure distribution and
slice artifacts, but it does not answer a narrower retrieval question: when a
case needs multiple gold chunks, are failures mostly because the missing chunks
were just below top-10, because evidence spans multiple documents, or because a
same-document section needs expansion? Without that split, a reviewer cannot
tell whether the likely next lever is larger candidate pools / reranking,
hybrid retrieval, query decomposition, or parent-section expansion.

The raw inputs needed for this question already exist in local-only
`reports/real100/eval_summary.json::case_results`: `gold_chunk_ids`,
`gold_evidence`, `retrieved_chunks`, retrieval recall metrics, citation
coverage, and hardcase/format tags. Those rows may contain private document
identifiers and text previews, so ADR 0005 requires any committed artifact to
cross the boundary as counts and closed enum buckets only.

## Decision

Add `scripts/render_multi_chunk_evidence_failures.py` as a read-only renderer
that consumes local `eval_summary.json` and emits
`reports/real100/multi_chunk_evidence_failures.aggregate.json`.

The aggregate schema is `schema_version: 1` and contains only source
provenance, population counts, top-k retrieval outcome buckets, same-doc vs
multi-doc split, structured-data overlap buckets, candidate-pool replay counts,
expected-impact counts, and citation guardrail counts. A multi-chunk case is an
answerable case with at least two unique gold chunk IDs. Candidate-pool replay
uses only the stored retrieved order; if a missing gold chunk is not present in
that stored order, the renderer records limited observability instead of
guessing beyond the saved depth.

## Consequences

- The new artifact can support claims about whether multi-chunk failures look
  pool/rerank-bound, decomposition-bound, or section-expansion-bound without
  committing private raw content.
- Runtime RAG behavior is unchanged: no retrieval, verifier, prompt, chunking,
  or answer path imports this renderer.
- The aggregate intentionally cannot prove that a larger live candidate pool
  would recover chunks not present in the saved retrieved order; those cases
  remain `unknown_due_to_limited_depth`.
- `.gitignore` and `.githooks/pre-commit` allowlist exactly the aggregate JSON
  filename; raw `eval_summary.json` and per-case diagnostics stay ignored.

## Alternatives considered

- **Add fields to `eval/run_eval.py`**: rejected for this PR because the goal is
  analysis-only and no retrieval behavior or eval runtime surface needs to
  change.
- **Commit per-case anonymized rows**: rejected because chunk/cardinality joins
  can re-identify private cases; counts-only is sufficient for the reviewer
  question.

## Verification

<!-- verifies-key: scripts/render_multi_chunk_evidence_failures.py:def build_aggregate -->
<!-- verifies-key: tests/test_render_multi_chunk_evidence_failures.py:PrivacyBoundaryTest -->
<!-- verifies-key: .gitignore:multi_chunk_evidence_failures.aggregate.json -->
