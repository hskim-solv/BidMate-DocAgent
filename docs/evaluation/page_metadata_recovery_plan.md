# Page Metadata Recovery Plan

## TL;DR

Current difficulty profiling says the hard benchmark is difficult but not
invalid. Naive dense-only retrieval is not completely broken, and the dominant
bottleneck is now page metadata / citation grounding infrastructure.

This plan moves the page metadata surface from audit-only NO-GO to an
implementation-ready roadmap. It does not change retrieval, verifier, prompt,
chunking, reranker, or answer runtime behavior.

Single recommendation: **full re-index** after page-aware parser output exists.

Phase A is now explicitly contract/adapter/test/docs only. It adds the
page-aware parser output contract documented in
[`page_aware_parser_contract.md`](page_aware_parser_contract.md), but does not
perform a full re-index and does not change retrieval, verifier, prompt,
reranker, answer generation, citation selection, or other RAG runtime behavior.

## Current Boundary

| boundary | current page metadata state | readiness implication |
|---|---|---|
| parser output | Visual artifacts can carry `pages`, `blocks`, `regions`, and `page_span`; CSV/kordoc text path usually emits plain text sections only. | Page recovery must start before indexing. |
| kordoc/HWP extraction | Kordoc Markdown preserves text/table structure but current cache manifest is not a page map. | HWP needs page-aware parser support or a render-to-visual path. |
| PDF extraction | Visual ingestion can emit page/block metadata; kordoc/csv-text PDF path may not. | PDFs are the best Phase A candidate when visual artifacts exist. |
| chunk serialization | `rag_indexing` already preserves optional `regions` and `page_span` from sections to chunks. | Contract exists; coverage is the missing piece. |
| index build payload | `index.json` schema v2 can store optional chunk/parent page metadata. | Re-index is required once parser output is page-aware. |
| eval summary rendering | Citation page/region coverage and precision aggregates already exist. | Re-evaluation can stay aggregate-only. |
| citation renderer | `make_citation()` already propagates optional `regions` and `page_span`. | No citation selection or answer behavior change is required. |
| parser output contract | `sections[].page_span` and `sections[].regions[].page_number` now have a fail-loud validation surface. | Re-index remains blocked until validated parser output coverage is greater than zero. |

## Recoverability

| evidence source | recoverability |
|---|---|
| Current chunks have `page_span` or `regions.page_number` | Recoverable from current index for covered source groups. |
| Parent sections have page metadata but chunks do not | Recoverable via rechunk/re-index. |
| Visual artifacts have page/block metadata | Recoverable via visual-artifact-based re-index. |
| Kordoc cache has page markers | Possibly recoverable after adapter spike. |
| Chunk offsets only | Not recoverable today; source page boundaries and chunk character offsets are not stored. |
| HWP/PDF kordoc or CSV text without page markers | Requires page-aware parser output and full re-index. |

## Implementation Matrix

| source type | current coverage | recoverable? | requires parser change? | requires re-index? | requires OCR/visual ingestion? | estimated engineering cost | expected eval impact |
|---|---:|---|---|---|---|---|---|
| Existing index with no page fields | 0% | No | No | Yes | No | S | Enables coverage measurement only after rebuild. |
| Existing index with parent-only page fields | parent >0%, chunk 0% | Yes, via rechunk | No | Yes | No | S-M | Citation page coverage can become GO for covered groups. |
| Visual PDF/image artifacts | artifact page/block coverage >0 | Yes | No | Yes | Already visual | M | Strongest near-term page citation lift for PDFs/images. |
| PDF via kordoc/csv-text with no markers | 0% | No | Yes or visual path | Yes | Prefer visual for scanned/weak text-layer PDFs | M-L | Page citation GO only after parser output carries page spans. |
| HWP via kordoc with no markers | 0% | No | Yes | Yes | Usually no, unless rendered to PDF/images | M-L | Page citation GO requires page-aware HWP extraction or render+visual path. |
| CSV text fallback | 0% | No | No for fallback; raw source reparse needed | Yes | Depends on source | S-M | Low confidence unless raw source can be reparsed. |
| Public JSON/MD fixtures | 0% unless authored | Yes if fixture sections include page fields | No | Yes | No | S | Useful regression fixture, not a real performance claim. |

## Roadmap

Phase A: restore page metadata only.

- Run `scripts/page_metadata_recovery_audit.py` against local private index and optional local artifacts.
- Keep outputs aggregate-only and commit no raw private text, evidence, filenames, `doc_id`, `chunk_id`, or local paths.
- Rebuild a page-aware index only after parser output has `sections[].page_span` or `sections[].regions`.
- Validate parser section output with `parser_page_metadata_contract.py`; malformed page metadata fails loudly, while missing page metadata is allowed and counted as uncovered.
- Treat Phase A as contract/adapter/test/docs only. Full HWP/PDF parsing and full re-index remain follow-up work.

Phase B: page-aware chunk serialization.

- Preserve `page_span` and `regions` through section normalization, parent sections, chunks, index write/load, evidence, and citations.
- Validate page spans as `[start:int, end:int]` with `start <= end`.
- Validate region page numbers fall inside span when both are present.

Phase C: page-grounded citation rendering and re-evaluation.

- Use existing citation propagation; do not change citation selection.
- Re-run aggregate-only `citation_page_coverage`, `citation_page_precision`, and citation coverage reason counts.
- Mark citation/page claims GO only for source groups with non-zero page metadata coverage and compatible explicit page gold.

Phase D: optional visual/table-aware ingestion.

- Prefer visual ingestion for PDFs/images where text-layer or kordoc output lacks page markers.
- Treat HWP visual rebuild as a separate spike: page-aware HWP parser or HWP-to-PDF/image render plus visual ingestion.
- Table and bbox precision are optional and should not block Phase A page-span recovery.

## Readiness Checks

- `page_metadata_coverage_gt_0`: at least one chunk has `page_span` or `regions.page_number`.
- `parser_output_page_metadata_coverage_gt_0`: at least one parser section has valid `page_span` or `regions.page_number`.
- `chunk_page_span_integrity`: page spans are valid and region pages do not fall outside spans.
- `citation_renderer_compatible`: existing renderer can propagate page metadata without behavior changes.
- `no_private_path_leakage`: committed artifacts omit exact local paths and filenames.
- `aggregate_only_outputs`: reports contain counts, rates, source categories, and decisions only.

## GO Criteria

Citation/page claims can become GO only after recovery for the covered source
groups. A global GO requires non-zero page metadata coverage across the target
evaluation slice and explicit page gold for citation precision. Until then,
page-level citation claims remain NO-GO even if Recall@K improves.

Recommendation: **full re-index**.
