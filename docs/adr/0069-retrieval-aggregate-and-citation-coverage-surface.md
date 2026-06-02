# 0069: Retrieval aggregate + citation coverage + embedding versioning as eval_summary surface

- **Status**: accepted
- **Date**: 2026-05-22
- **Deciders**: hskim (solo author)
- **Related**: ADR 0005 (eval split / commit boundary), ADR 0048 (realN metrics extension), ADR 0054 (conditional-on-answer scorer semantics), ADR 0059 (failure-mode classifier surface)

## Context

The repo already computes chunk-level retrieval metrics per case
(`chunk_recall_at_{5,10,20}` / `chunk_mrr_at_5` / `chunk_mrr` /
`chunk_ndcg_at_{5,10,20}` /
`rerank_delta_*` in `eval/scorers/case.py`) but never aggregated them — there
was no run-level mean + CI in `reports/eval_summary.json`. Comparing a candidate
embedding / reranker / chunking / parsing backend against the baseline therefore
required hand-summing per-case rows, which is exactly the friction that blocks
the planned ablation sweep (KURE / bge-m3-korean / Qwen3 embeddings, new
rerankers, query-transformation). A measurement surface has to exist *before*
those backends are wired in, or "recall +Xpp vs baseline" cannot be read off in
one line.

Two adjacent gaps surfaced at the same time: (1) citation quality was only
scored against gold (`citation_*_precision`), so a backend that simply stopped
attaching page/region metadata could not be caught on cases without gold
citations; and (2) `run_manifest` pinned `git_commit` + `config_sha256` but not
the embedding model — which lives in the *index*, not the config — so an
eval_summary snapshot was not self-describing about which embedding produced its
retrieval numbers.

## Decision

Expose three deterministic, LLM-free measurement surfaces in
`reports/eval_summary.json`, all reusing the existing aggregate plumbing
(`metric_block` + `eval/bootstrap.py::bootstrap_ci`, `rate`):

1. **Retrieval aggregate** — `metric_block` folds the per-case chunk metrics
   into a run-level mean (`block[key]`) + bootstrap CI (`block["ci"][key]`) for
   `chunk_recall_at_{5,10,20}`, `chunk_mrr_at_5`, `chunk_mrr`,
   `chunk_ndcg_at_{5,10,20}`,
   `rerank_delta_mrr`, `rerank_delta_ndcg_at_10`. Every key is always emitted;
   `None`-valued (gold-free) cases are skipped, and an all-`None` slice reports
   `None` mean + `None` CI rather than a fabricated 0.0. Because `metric_block`
   is applied to every slice via `summarize_run`, these keys propagate to
   `by_query_type` / `by_hardcase_category` / `by_metadata_field` / `by_format`
   with no extra code.

2. **Citation coverage** — `eval/scorers/citation.py::score_citation_coverage`
   emits gold-free `citation_claim_coverage` (fraction of claims carrying a
   citation), `citation_page_coverage`, `citation_region_coverage` (fraction of
   citations that actually fill page / bbox metadata). `None` when the
   denominator is empty (no claims / no citations), so well-formed abstentions
   are excluded — consistent with ADR 0054.

3. **Embedding versioning** — `compute_run_manifest` records
   `embedding_backend` + `embedding_model_id` read from the loaded index's
   `embedding` block; `None` when absent (forward-compat).

## Consequences

- **Locked contract**: `reports/eval_summary.json` headline and every by-slice
  block carry the chunk + coverage keys above, each with a parallel entry under
  `block["ci"]`; `run_manifest` carries `embedding_backend` /
  `embedding_model_id`. Downstream consumers (aggregate report, README metrics,
  baseline regression) may rely on these keys existing (value may be `None`).
- **ADR 0005 boundary**: all new keys are numeric means / counts / CI bands —
  no per-case text — so the aggregate crosses the private-real commit boundary
  intact, exactly as ADR 0048's `abstention_outcomes` does. No scanner allowlist
  change is required; the boundary forbids per-case text leakage, not numeric
  aggregates.
- **ADR 0001**: ranking functions are untouched; only the eval read-side grows,
  so the `naive_baseline` byte-identity invariant is unaffected.
- **Cost**: every slice now serialises ~9 extra float keys + CI bands. Negligible
  for JSON size; the bootstrap is already run for the answer-quality metrics.
- **Out of scope (follow-up PR)**: surfacing RAGAS `context_precision` /
  `context_recall` (LLM-judge, retired RAGAS enrichment boundary) into the aggregate CI — that
  is a separate concern with a live-backend dependency.

**2026-05-24 update:** RFP QA naive-baseline measurement added explicit
`MRR@5` and `nDCG@5`, plus raw `retrieved_chunks` diagnostics and failure-case
JSONL artifacts. This extends the measurement surface without adding rerank,
hybrid search, query rewriting, or verifier retry to `naive_baseline`.

## Alternatives considered

- **Aggregate in a separate script** (like `eval/llm_judge.py` writes
  `judge_ragas`): rejected — the per-case values already live in `case_results`,
  so a second pass would duplicate plumbing and risk drift from the headline.
- **Record embedding model in the config + config_sha256 only**: rejected — the
  embedding model is chosen at index-build time and is not in `eval/config.yaml`,
  so `config_sha256` cannot capture it; the index is the single source of truth.
- **Gold-scored coverage only**: rejected — the point of coverage is to catch
  metadata-plumbing regressions on cases that lack page/region gold, which a
  gold-scored metric structurally cannot.

## Verification

<!-- verifies-key: reports/eval_summary.json:chunk_recall_at_5 -->
<!-- verifies-key: reports/eval_summary.json:chunk_mrr_at_5 -->
<!-- verifies-key: reports/eval_summary.json:chunk_mrr -->
<!-- verifies-key: reports/eval_summary.json:chunk_ndcg_at_5 -->
<!-- verifies-key: reports/eval_summary.json:citation_claim_coverage -->
<!-- verifies-key: reports/eval_summary.json:embedding_model_id -->

Regression tests pin the behavior: `tests/test_chunk_aggregate_regression.py`
(mean + CI emitted, `None`-skip, keys always present),
`tests/test_citation_coverage_regression.py` (gold-free coverage + aggregate
`None`-skip), `tests/test_run_manifest_versioning_regression.py` (embedding
fields from index, `None` when absent). `make smoke` regenerates
`reports/eval_summary.json` and the keys above appear in the headline block.
