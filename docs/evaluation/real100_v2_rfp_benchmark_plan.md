# real100_v2 RFP Benchmark Rebuild Plan

This document defines the public-safe plan for rebuilding the private RFP benchmark from PyMuPDF4LLM parsed artifacts. It is for interpretation and comparison, not cherry-picking headline claims.

## Purpose

The current real-eval aggregate mixes easy sanity checks with hard parser/retrieval stress cases. `real100_v2` separates those cases up front so future PRs can report overall performance plus each difficulty tier.

## Privacy Boundary

Committed artifacts may include only aggregate counts, closed labels, schema metadata, and high-level protocol text. Do not commit raw questions, answers, evidence text, document IDs, chunk IDs, filenames, local paths, per-case rows, converted PDFs, parsed Markdown, or raw eval summaries.

Private local artifacts belong under ignored `data/private/real100_v2/`, `data/index/real100_v2/`, and ignored raw report paths. Public aggregate outputs belong under the explicit `reports/real100_v2/` allowlist.

## Recommended Size

Recommended target: 300 cases.

| tier | count | purpose |
|---|---:|---|
| `easy_sanity` | 60 | Detect broken indexing/retrieval on answerable single-doc, single-chunk cases. |
| `standard_real` | 150 | Represent normal RFP QA: date, amount, score, requirement, eligibility, deliverable, and moderate distractor cases. |
| `hard_stress` | 90 | Preserve hard cases without letting them swallow the benchmark: multi-chunk, multi-doc, table/gantt-like, parser-stress, similar-clause, citation-dependent, and unanswerable cases. |

This is large enough for tier-level movement to be visible while keeping local eval runtime close to the existing real-eval scale.

## Tier Criteria

`easy_sanity`:

- answerable
- single-doc
- single-chunk
- clear expected terms
- no table-heavy evidence
- no multi-hop
- no similar-clause distractor proxy

`standard_real`:

- normal RFP QA cases
- may include date, amount, score, schedule, requirement, eligibility, or deliverable extraction
- may include moderate distractors
- must not require multi-doc, multi-chunk, table-heavy, parser-stress, or citation/page-dependent reasoning

`hard_stress`:

- multi-chunk
- multi-doc comparison
- table-heavy or gantt/schedule-like evidence
- similar-clause distractors
- unanswerable
- citation/page dependent
- image-only, low-text, or poorly parsed document regions selected from converted PDF review

Unanswerable cases stay in `hard_stress` for headline tiering, but they should be capped near 10 percent of the full benchmark and reported separately in `answerability` aggregates.

## Question Composition

Suggested target mix:

| slice | target |
|---|---:|
| easy single-chunk content anchors | 60 |
| standard date/schedule extraction | 35 |
| standard amount/budget extraction | 35 |
| standard score/evaluation extraction | 30 |
| standard RFP requirement/eligibility/deliverable extraction | 50 |
| hard multi-chunk same-doc | 27 |
| hard multi-doc comparison | 14 |
| hard table/gantt/parser-stress | 23 |
| hard unanswerable/absence | 26 |

The deterministic proposer can draft the text-grounded subset from parsed Markdown. Answerable visual/parser-stress cases require local review of converted PDFs before promotion, because image-only or badly structured pages cannot be gold-labeled from Markdown alone.

## Baseline Validation Protocol

1. Rebuild the local private parse/index with PyMuPDF4LLM using OCR and layout enabled. Use `scripts/build_private_real100_v2_parallel.py` for the rebuild so document parsing can run in parallel. The builder writes private per-row checkpoints under the ignored index output by default, so long OCR/layout runs can be stopped and resumed without committing raw parsed text. A per-document timeout may be used to prevent a single malformed document from blocking the run; timed-out documents become parser-stress candidates.
2. Export parsed Markdown to ignored private storage and write `reports/real100_v2/parse_inventory.aggregate.json`.
3. Generate private draft questions and write `reports/real100_v2/question_distribution.aggregate.json`.
4. Run the private eval dataset audit. It must pass with no label/index-reference errors before baseline measurement.
5. Run baseline retrieval/eval against `data/index/real100_v2/`; keep raw `eval_summary.json` ignored.
6. Render aggregate-only baseline and tier summaries.
7. Future PRs must report overall plus all tiers. A PR must explain tier regressions and must not select only improved tiers for claims.

## Non-Goals

- No retrieval, verifier, prompt, chunking, reranker, answer generation, or runtime behavior change.
- No public raw benchmark release.
- No performance claim from the rebuild itself until the baseline is measured and aggregate outputs pass privacy checks.
