# 0102: Parser Element Micro-Eval Wiring Surface

- **Status**: accepted
- **Date**: 2026-06-05
- **Deciders**: User, Codex
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (aggregate-only eval boundary), [ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md) (retrieval aggregate precedent), [ADR 0078](./0078-pymupdf4llm-canonical-page-citation.md) (PyMuPDF4LLM remains citation control)

## Context

The parser/OCR/VLM roadmap introduced a private 12-doc parser element stream
that merges `metadata_fact`, PyMuPDF4LLM text-layer control, table sidecars, and
routed OCR sidecars without changing canonical ingestion defaults. The first
retrieval smoke proved wiring, but it was still easy to over-read as parser
quality evidence or to hide query ambiguity behind good-looking aggregate
numbers.

The row-48 compliance-table probe exposed that risk: generic checklist wording
appeared across multiple RFPs, so the initial top-1 miss was a query/expected
fact ambiguity rather than a parser routing failure. After query disambiguation
and same-hit hardening, the rerun produced `6/6` same-hit pass, `6/6` top-1 row
hits, `5/6` top-1 same-hit matches, and same-hit MRR `0.875`, with
metadata/OCR/table/text-layer source coverage and textless aggregate reporting.

This is useful enough to be a reviewer-facing regression surface, but it must
remain narrow. It measures element wiring and searchability, not OCR accuracy,
PDF parser quality, chart/diagram semantics, real100_v2 answer quality, or
canonical ingestion readiness.

## Decision

Promote `parser_element_micro_eval_v0` as an official reviewer-facing wiring
regression surface for parser element streams, with the following contract:

1. **Fixed query set.** The v0 query set lives at
   `data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json` and is pinned by
   SHA-256 hash
   `72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5`.
2. **Fixed current artifact family.** The current v0 evidence uses routing-v2
   element stream
   `parser-element-stream-12doc-routing-v2-20260605T092518Z` and aggregate
   report
   `reports/parser_candidate_eval/parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z/retrieval_smoke.aggregate.json`.
3. **Metrics.** The surface reports pass count, same-hit pass, top-1 same-hit
   matches, top-1 row hits, same-hit MRR, source coverage, expected element type
   coverage, declared rows, effective rows, and alias rows. The aggregate run
   block also records the fixed `query_set_hash` so reviewer artifacts are
   self-describing. The current acceptance floor is all queries pass with row
   and expected element type matching the same hit, all queries are top-1 row
   hits, same-hit MRR is at least `0.875`, and the only permitted top-1
   same-hit miss is the known `text_row48_compliance_table` alias/boilerplate
   case. Any additional top-1 same-hit miss is a regression.
4. **Alias policy.** Path rows are strict by default. Source-sha alias scoring is
   opt-in per query via `allow_source_sha256_alias: true` and must report
   declared/effective/alias rows separately.
5. **Aggregate boundary.** Reviewer artifacts are textless: query names and
   hashes may appear, but raw query text and raw chunk text stay in private
   local artifacts under `data/private/real100_v2/...`.
6. **Claim boundary.** Allowed claim: parser element stream wiring/searchability
   for metadata, routed OCR, table sidecars, text-layer control, and path alias
   scoring did or did not regress. Disallowed claims: parser quality improved,
   OCR accuracy improved, real100_v2 retrieval/answer quality improved,
   VLM/chart/diagram extraction is adequate, or PyMuPDF4LLM can be replaced.

The validator is `scripts/validate_parser_element_micro_eval_surface.py`. It is
the gate for citing this surface in parser/ingestion reviewer evidence.

## Consequences

- **+** Parser/metadata/OCR/table work gets a small deterministic reviewer
  surface that catches searchability and provenance regressions before a large
  private real-eval run.
- **+** Query ambiguity and alias/copy behavior are explicit: query-set drift
  changes the hash, and alias scoring cannot silently widen row matches.
- **+** The surface stays aggregate-only and reviewer-safe; raw text remains in
  private generated artifacts.
- **−** This is not a benchmark for extraction quality. A passing result can
  coexist with bad OCR, malformed table structure, or poor chart/diagram
  understanding.
- **−** The surface adds a maintained query-set hash and validator. Any v1 query
  expansion needs a deliberate hash update and reviewer-facing rationale.
- **−** It does not change canonical ingestion defaults. Replacing
  PyMuPDF4LLM, enabling OCR/VLM by default, or making parser output part of
  answer citations still requires separate ADR/eval evidence.

## Alternatives considered

- **Leave as ad-hoc harness only.** Rejected: the harness already has a fixed
  query set, source/type coverage, textless aggregate, validator, and rerun
  evidence; keeping it informal would lose a useful regression signal.
- **Promote as parser quality benchmark.** Rejected: the evidence only proves
  emitted elements are searchable. It has no human OCR/table/chart ground truth
  and no real100_v2 answer-quality delta.
- **Make it a CI-required gate immediately.** Rejected for now: the artifact is
  private/generated and tied to a 12-doc real100_v2 subset. Use it as reviewer
  evidence first; CI promotion would need a separate public or committed
  aggregate strategy.

## Verification

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --element-stream data/private/real100_v2/parser_element_stream/parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json \
  --queries-json data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json \
  --run-id parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z \
  --top-k 6
python3 scripts/validate_parser_element_micro_eval_surface.py
python3 -m pytest tests/test_validate_parser_element_micro_eval_surface.py tests/test_parser_element_stream_retrieval_smoke.py -q
```

<!-- verifies-key: scripts/validate_parser_element_micro_eval_surface.py:parser_element_micro_eval_v0 -->
<!-- verifies-key: scripts/validate_parser_element_micro_eval_surface.py:72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5 -->
<!-- verifies-key: docs/evaluation/surface-map.md:Parser element micro-eval -->
