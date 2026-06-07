# T-2026-0081 — Parser output merge schema and routing contract

- ID: T-2026-0081-merge-schema
- Status: draft contract
- Created: 2026-06-05
- Parent plan: [`T-2026-0081-parser-ocr-vlm-routing-roadmap.md`](T-2026-0081-parser-ocr-vlm-routing-roadmap.md)
- Evidence inputs:
  - `page-audit-96path-table-capped-20260605T074915Z`
  - `page-audit-96path-routing-v2-20260605T092124Z`
  - `ocr-mini-review-row16-row17-20260605T074054Z`
  - `parser-12doc-ocr-off-smoke-20260605T050845Z`
  - `parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z`

## Purpose

Define the merge contract before OCR/table/VLM outputs enter canonical RAG
chunking. This is a contract document, not an ingestion-default change.

The central rule is: **preserve citation traceability and path-level metadata over
extraction volume**. Extra parser outputs are useful only when they can be tied to
`csv_row`, path alias, page, provider, and extraction mode.

## Non-negotiable invariants

1. **Path aliases are separate documents.** Byte-identical PDFs with different
   `csv_row`/path metadata remain separate `doc_id`s.
2. **Metadata is RAG data.** `csv_row`, `source_file`, `path_pdf`,
   `source_sha256`, and CSV metadata fields must survive into every document
   artifact and chunking boundary.
3. **Page traceability gates citation readiness.** Elements without reliable
   `page_span` cannot support citation-bearing answers.
4. **Parser provenance is first-class.** Candidate/provider/model/version/date,
   route trigger, runtime, and opt-in flags are stored with each element or batch.
5. **No canonical replacement by harness result alone.** PyMuPDF4LLM remains the
   citation control until an ADR/reviewer-facing eval promotes a new default.

## Document artifact schema

```json
{
  "schema_version": 1,
  "mode": "parser_element_stream",
  "doc_id": "real100_v2:path:<csv_row>:<path-slug>",
  "csv_row": 16,
  "source_file": "...hwp",
  "path_pdf": "data/private/real100_v2/converted_pdfs_by_path/...pdf",
  "source_sha256": "...",
  "metadata": {
    "csv": {},
    "normalized": {}
  },
  "route_summary": {
    "page_audit_run_id": "page-audit-96path-routing-v2-20260605T092124Z",
    "route_counts": {},
    "label_counts": {}
  },
  "elements": []
}
```

## Element schema

```json
{
  "element_id": "<doc_id>:<candidate>:p0001:<kind>:<ordinal>:<hash8>",
  "element_type": "text_layer|table|ocr_text|figure|chart|diagram|formula|metadata_fact",
  "source_role": "control|sidecar|routed_ocr|routed_vlm|metadata",
  "page_span": [1, 1],
  "bbox": [0.0, 0.0, 100.0, 100.0],
  "text": "citation-bearing plain text when available",
  "structured_payload": null,
  "confidence": null,
  "citation_ready": true,
  "merge_priority": 10,
  "route_labels": ["ocr_needed"],
  "provenance": {
    "candidate": "pymupdf4llm_text_control|pdfplumber_table_sidecar|paddleocr_classic|tesseract_baseline|pp_structurev3_local|paddleocr_vl_local|paddleocr_official_api",
    "provider": "local|hosted_api|metadata",
    "candidate_version": "...",
    "model": "...",
    "generated_at_utc": "YYYYMMDDTHHMMSSZ",
    "run_id": "...",
    "runtime_s": 0.0,
    "cost_usd": 0.0
  }
}
```

## Element type rules

| element_type | allowed source | citation_ready rule | notes |
|---|---|---|---|
| `text_layer` | PyMuPDF4LLM/PyMuPDF text control | true when page_span exists | default citation backbone |
| `table` | pdfplumber/PyMuPDF/PP-StructureV3 table sidecar | true when page_span exists and table text/cells are grounded | store markdown/html/cell JSON in `structured_payload` |
| `ocr_text` | PaddleOCR/Tesseract routed OCR | true only for routed pages with page_span and retained provider confidence/provenance | do not run document-wide by default |
| `figure` | VLM/document parser | false unless summary is directly page-grounded and reviewer-approved | labels/captions may be text; semantics need care |
| `chart` | VLM/document parser | false by default; promote only after chart eval | axes/legend/value claims need explicit structured payload |
| `diagram` | VLM/document parser | false by default; promote only after diagram eval | arrows/dependencies are high hallucination risk |
| `formula` | PP-StructureV3/VLM | true only if source parser returns grounded expression and page_span | keep original + normalized form |
| `metadata_fact` | CSV/path metadata | true for metadata questions; page_span may be null | answer layer must cite metadata provenance differently from page evidence |

## Merge priority

Lower number wins for primary chunk text ordering; sidecars are retained even when
not primary.

1. `metadata_fact` for metadata-only facts.
2. `text_layer` from citation control.
3. `table` sidecars for detected/table-routed pages.
4. `ocr_text` for pages whose audit label includes `ocr_needed` or whose text
   control is empty/low quality.
5. `figure`/`chart`/`diagram` summaries for VLM-routed pages, initially
   non-citation-ready unless manually/eval-approved.

## De-duplication

- De-dup only within the same `doc_id` and page.
- Never de-dup across different `csv_row` path aliases even when
  `source_sha256` is identical.
- Candidate outputs that normalize to the same text hash should keep all
  provenance but only one text body should be primary for chunking.
- OCR text should not overwrite text-layer text. It is additive unless a page is
  text-layer empty/low quality.

## Routing policy from current evidence

Use `page-audit-96path-routing-v2-20260605T092124Z` as routing surface:

- `text_layer`: default for `8249` primary pages.
- `ocr_needed`: `504` primary pages; `657` overlapping OCR labels.
- `vlm_needed`: `227` primary/overlap pages after the
  `vlm-image-count-min-area-ratio=0.05` false-positive reduction.
- `table_sidecar`: `124` capped primary pages; do not treat as full table
  coverage truth.
- `manual_review`: `3` primary pages.

Recommended first implementation:

1. Build element stream for 12-doc subset only.
2. Include `metadata_fact`, `text_layer`, `pdfplumber_table_sidecar`, and routed
   OCR outputs for reviewed/tiny OCR pages.
3. Keep VLM elements out of canonical chunks until hosted/remote VLM produces a
   small reviewed sample.
4. Add micro-eval queries for metadata, OCR page facts, and table facts before
   changing canonical retrieval defaults.

## ADR / eval gate

Create or update an ADR before any of the following:

- replacing PyMuPDF4LLM as canonical citation parser,
- making OCR or VLM default-on,
- treating parser candidate reports as reviewer-facing measurement surfaces,
- allowing non-page-grounded figure/chart/diagram summaries into citation-bearing
  answers.

## Micro-eval reviewer-surface rules

The 12-doc parser element retrieval smoke is still a harness. Before promoting
it to a reviewer-facing measurement surface, keep these rules:

1. **Query rows are explicit.** Each query declares `expected_rows` and
   `expected_element_types`; row-less probes are allowed only for ad-hoc
   debugging, not scored micro-eval reports.
2. **Avoid boilerplate-only queries.** A query that targets a repeated RFP table
   or checklist must include project/agency/title terms plus the specific fact
   terms. The row-48 compliance query is the current example.
3. **Alias scoring is opt-in.** Default scoring is path-row strict. Set
   `allow_source_sha256_alias: true` only when the evaluation intent is “same
   source bytes under path aliases,” and report declared rows, effective rows,
   and alias rows separately.
4. **Aggregate reports are textless.** Public/reviewer aggregate artifacts use
   query names and query hashes, not raw query text or chunk text. Raw index text
   remains under `data/private/real100_v2/...`.
5. **No default-change claim from this surface alone.** Passing this micro-eval
   proves local wiring/query coverage only; canonical ingestion changes still
   need ADR/reviewer policy plus real100_v2 aggregate evidence.

## Parser element micro-eval v0 gate

Surface name: `parser_element_micro_eval_v0`.

Validation command:

```bash
python3 scripts/validate_parser_element_micro_eval_surface.py
```

Current fixed query-set hash:

```text
72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5
```

The aggregate `run.query_set_hash` must record this same value so reviewer
artifacts are self-describing even when the private/local query JSON is not
committed.

Current evidence artifact:

- Aggregate:
  `reports/parser_candidate_eval/parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z/retrieval_smoke.aggregate.json`
- Private index:
  `data/private/real100_v2/parser_element_retrieval_smoke/parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z/index/index.json`

What this surface measures:

- Metadata facts survive into RAG-indexable elements.
- Routed OCR sidecar elements are indexable.
- Table sidecar elements are indexable.
- Text-layer control elements remain indexable.
- Path aliases can be scored row-strict by default or source-sha alias-aware
  when explicitly requested.
- Aggregate output remains reviewer-safe and textless.

What this surface does **not** measure:

- Overall `real100_v2` retrieval/answer quality.
- OCR accuracy against human ground truth.
- Table structure quality beyond searchability of emitted sidecar text.
- Chart, diagram, form, or figure semantic extraction quality.
- Whether PyMuPDF4LLM should be replaced as the canonical citation parser.
- Whether OCR/VLM should become default-on.

Use conditions:

1. This gate passes on a fresh rerun with the fixed query-set hash.
2. The claim wording remains “parser element wiring/searchability regression
   guard,” not parser quality or real-world performance.
3. A reviewer-facing aggregate stays textless and commit-safe.
4. PRs cite [ADR 0102](../adr/0102-parser-element-micro-eval-wiring-surface.md)
   before using this as reviewer evidence.
