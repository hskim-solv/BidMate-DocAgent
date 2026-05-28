# real100_v2 Page Metadata Recovery Audit

## Decision
- Citation page claim: `NO-GO`
- Private real-eval index: `NO-GO`
- Private real-eval index no-go reasons: `hashing_embeddings_forbidden, minilm_semantic_baseline_required, chunk_page_metadata_coverage_zero`
- Recoverability: `not_recoverable_from_existing_artifacts`
- Requires re-index: `True`
- Requires parser change: `False`
- Retrieval/verifier/prompt/answer behavior change: `False`
- Embedding backend/model/dim: `hashing` / `local-hashing-bow` / `384`

## Coverage
- Documents / chunks / parent sections: `100` / `21800` / `100`
- Chunk page metadata coverage: `0.0`
- Chunk page_span coverage: `0.0`
- Chunk regions.page_number coverage: `0.0`
- Chunk regions.bbox coverage: `0.0`

## Source Groups
- `file_format=hwp, text_source=pdf_pymupdf4llm, document_type=private_pdf_hwp_csv_text, chunking_strategy=fixed`: docs=`96`, chunks=`20391`, parents=`96`, page=`0.0`, page_span=`0.0`, regions.page_number=`0.0`, regions.bbox=`0.0`, capability=`page_blind`, decision=`requires_page_aware_reindex`
- `file_format=pdf, text_source=pdf_pymupdf4llm, document_type=private_pdf_hwp_csv_text, chunking_strategy=fixed`: docs=`4`, chunks=`1409`, parents=`4`, page=`0.0`, page_span=`0.0`, regions.page_number=`0.0`, regions.bbox=`0.0`, capability=`page_blind`, decision=`requires_page_aware_reindex`

## Implementation Matrix
| source type | current coverage | recoverable? | parser change? | re-index? | OCR/visual? | cost | expected eval impact |
|---|---:|---|---|---|---|---|---|
| `existing_index_with_no_page_fields` | 0.000000 | False | False | True | False | S | Enables coverage measurement only after rebuild. |
| `existing_index_with_no_page_fields` | 0.000000 | False | False | True | False | S | Enables coverage measurement only after rebuild. |

## Readiness Checks
- Page metadata coverage > 0: `False`
- Chunk page_span integrity: `True` (checked=`0`, invalid=`0`, region_outside=`0`)
- Citation renderer compatible: `True`
- No private path leakage: `True`
- Aggregate-only outputs: `True`

## Follow-Up Issue Plan
- Keep page-level citation claims disabled while source-group page coverage is zero.
- Run a page-aware rebuild spike for page-blind PDF and HWP source groups and verify non-zero regions.page_number coverage.
- Evaluate page-aware HWP extraction or an adapter that emits sections[].regions or sections[].page_span.
- Rebuild the private index only after page-aware parser output populates sections[].regions or sections[].page_span.
- Commit only aggregate reports; keep private raw content, filenames, doc_ids, and source paths out of artifacts.

## Recommendation
`full re-index`
