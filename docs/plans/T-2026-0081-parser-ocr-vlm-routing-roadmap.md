# T-2026-0081 — Parser OCR/VLM routing roadmap for RFP PDFs

- ID: T-2026-0081
- Title: Parser OCR/VLM routing roadmap for RFP PDFs
- Status: ready
- Priority: P0
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
- Created: 2026-06-05
- Last updated: 2026-06-05
- Related artifacts:
  - `.omx/context/pdf-parser-candidate-coverage-12doc-eval-20260605T023238Z.md`
  - `.omx/plans/prd-pdf-parser-candidate-coverage-12doc-eval-20260605T023238Z.md`
  - `.omx/plans/test-spec-pdf-parser-candidate-coverage-12doc-eval-20260605T023238Z.md`
  - `.omx/context/pdf-parser-12doc-subset.json`

## Problem

The repo now has path-level HWP-converted PDFs and row metadata that must survive
into RAG. The next parser decision is not simply "turn OCR on" or "replace
PyMuPDF4LLM". The corpus has text-layer content, many tables, many embedded
image objects, and likely graph/diagram/chart content that classic OCR cannot
understand.

If these decisions remain only in chat, future agents may accidentally:

- run full-corpus Tesseract OCR by default and waste hours,
- compare PaddleOCR and PaddleOCR-VL as if they are the same class of tool,
- ignore charts/diagrams because they are not text OCR,
- collapse duplicate path aliases by `source_sha256`, or
- replace canonical citation ingestion without eval evidence.

## Recorded decisions

1. **PyMuPDF4LLM remains the citation control.** Use it as the text-layer / page
   citation baseline until a measured candidate wins. Do not replace canonical
   ingestion as part of the harness-only work.
2. **The first parser-eval control should run PyMuPDF4LLM with OCR off.** The
   current repo default has PyMuPDF4LLM OCR enabled when
   `BIDMATE_PYMUPDF4LLM_USE_OCR` is unset and defaults OCR language to `eng`.
   That is not a good 12-doc bake-off control for Korean RFP PDFs. Treat OCR as
   an explicit candidate/route, not the default control.
3. **Tesseract is only a baseline/fallback.** It is not the preferred Korean RFP
   OCR path and should not be used as a full-document default.
4. **PaddleOCR classic and PaddleOCR-VL are different candidates.**
   - PaddleOCR / PP-OCR is a text OCR provider: text boxes, recognized text,
     confidence, and coordinates.
   - PP-StructureV3 is a document parsing pipeline: layout, tables, formulas,
     charts, reading order, Markdown/JSON.
   - PaddleOCR-VL is a layout + VLM document parsing pipeline for complex
     elements such as tables, formulas, charts, and irregular document regions.
5. **OCR is page-selective, not document-wide by default.** Route only pages or
   regions that need OCR/VLM based on text density, image density, table/figure
   signals, and downstream eval failures.
6. **Charts, diagrams, and system architecture images require VLM/document-parser
   evaluation.** Classic OCR may recover labels but not chart values, axes,
   legend semantics, arrows, swimlanes, or dependency relationships.
7. **pdfplumber/PyMuPDF table sidecars are first-class diagnostics.** They help
   detect table-heavy pages and compare parser output, even if they do not become
   the final RAG parser.
8. **Postprocessing is required.** Candidate outputs must be normalized into
   page-bound elements with `page_span`, optional `bbox`, `element_type`, text or
   table payload, confidence when available, and provider/model/date provenance.
9. **Metadata remains RAG data.** `csv_row`, `path_pdf`, `source_file`, `source_sha256`,
   and CSV metadata fields must be carried through every parser artifact and RAG
   chunk. Do not collapse byte-identical PDFs with different path aliases.
10. **External/API parser candidates are allowed with explicit opt-in and
    provenance.** ADR 0102 removes the private-egress gate, but provider/model,
    date, cost, latency, and skip/failure reasons must be recorded.
11. **ADR trigger:** create or update an ADR before changing canonical ingestion
    defaults, replacing PyMuPDF4LLM, or promoting parser-candidate eval reports
    as a reviewer-facing measurement surface.

## Current corpus signals

From `.omx/context/pdf-parser-subset-heuristics-20260605.json` over the 96
path-level converted PDFs:

- Documents: 96
- Total pages in audit snapshot: 9107
- Documents with tables detected in first 3 pages: 91/96
- Total first-3-page table detections: 278
- Documents with sampled image objects: 95/96
- Sampled image objects: 2305
- Low-text/OCR-stress examples: rows 16, 62, 21, 96, 91
- Table-heavy examples: rows 32, 2, 99, 51, 62

Interpretation: the primary risk is not simply missing text. The hard surface is
layout/table/figure/chart understanding while preserving page citations and row
metadata.

## Roadmap

### Phase 0 — Stabilize the minimal harness

Goal: make the existing 12-doc harness cheap and deterministic enough to run.

- Update `scripts/run_parser_candidate_eval.py` so `pymupdf4llm_current` reads
  OCR env/options and defaults to OCR off for the evaluation control.
- Add explicit candidates:
  - `pymupdf4llm_text_control` or keep `pymupdf4llm_current` with OCR-off option
  - `pymupdf4llm_ocr_tesseract_kor_eng` only as an opt-in baseline
  - `pdfplumber_table_sidecar`
- Record OCR options in provenance.
- Re-run the 12-doc subset with PyMuPDF4LLM OCR off + pdfplumber sidecar.

Acceptance:

- 12-doc run completes without document-wide OCR stalls.
- Duplicate alias checks pass for rows 17/55 and 23/48.
- Aggregate report exists with candidate status and skip/failure reasons.

### Phase 1 — Page audit and routing signals

Goal: classify pages before OCR/VLM so expensive candidates run only where they
can add value.

For each PDF page, compute aggregate/local routing features:

- text chars, Hangul ratio, mojibake markers
- image object count and image area ratio when feasible
- table count / table cell density from pdfplumber or PyMuPDF sidecar
- candidate figure/chart/diagram signals from layout blocks or image-heavy pages
- section heading/read-order proxy
- parser failure/empty-page flags

Output:

- local per-page routing JSON under `data/private/real100_v2/parser_candidate_eval/<run_id>/`
- aggregate report under `reports/parser_candidate_eval/<run_id>/`

Acceptance:

- Every 12-doc page has a route label: `text_layer`, `table_sidecar`,
  `ocr_needed`, `vlm_needed`, `manual_review`, or `skip`.
- No raw text is needed in aggregate reports; counts and row/page categories are enough.

### Phase 2 — Classic OCR candidate

Goal: evaluate OCR for pages where text-layer extraction is weak.

Candidates:

- Tesseract `kor+eng` as baseline only.
- PaddleOCR / PP-OCR with `BIDMATE_PADDLE_LANG=korean` or the version-appropriate
  PaddleOCR 3.x API.

Run only on `ocr_needed` pages or sampled pages from low-text docs.

Metrics:

- OCR text length recovery vs text-layer control
- Hangul ratio improvement
- confidence distribution when available
- bbox availability
- runtime per page
- impact on retrieval/answer citations for OCR-stress queries

Acceptance:

- PaddleOCR beats or justifies replacing Tesseract for Korean OCR-stress pages,
  or the report records why it does not.
- OCR output can be normalized into page-bound elements without breaking `page_span`.

### Phase 3 — Document parser / VLM candidates for tables, charts, diagrams

Goal: evaluate non-OCR document understanding for information that text OCR alone
cannot represent.

First candidates:

- PP-StructureV3 for layout/table/formula/chart/read-order parsing.
- PaddleOCR-VL with chart recognition explicitly enabled for chart/diagram pages.
- One hosted parser/VLM candidate if credentials are configured: Upstage Document
  Parse, Mistral OCR, or LlamaParse.

Route only pages or regions with table-heavy, image-heavy, chart-like, diagram-like,
or text-layer failure signals.

Metrics:

- table structure preservation
- chart/diagram element presence and structured summary usefulness
- reading-order preservation
- page/bbox traceability
- hallucination/unsupported-content flags
- runtime/cost per page/region

Acceptance:

- At least one VLM/document-parser candidate produces useful structured evidence
  for chart/diagram/table-heavy pages without regressing citation traceability.
- If no candidate adds value, keep VLM routing disabled and record the negative result.

### Phase 4 — Postprocessing and merge layer

Goal: merge text-layer, table, OCR, and VLM outputs into a single RAG-ready element
stream without losing provenance.

Normalization target:

```json
{
  "doc_id": "real100_v2:path:<csv_row>:<path-stem>",
  "csv_row": 0,
  "source_sha256": "...",
  "path_pdf": "...",
  "metadata": {},
  "elements": [
    {
      "element_id": "...",
      "element_type": "paragraph|table|figure|chart|diagram|formula|ocr_text",
      "page_span": [1, 1],
      "bbox": null,
      "text": "...",
      "structured_payload": null,
      "confidence": null,
      "provenance": {
        "candidate": "...",
        "candidate_version": "...",
        "provider": "local|hosted",
        "model": "...",
        "generated_at": "..."
      }
    }
  ]
}
```

Acceptance:

- Duplicate path aliases remain separate `doc_id`s.
- Elements with no reliable page trace are excluded from citation-bearing answer
  paths or marked non-citation-ready.
- Downstream chunking can choose source priority without mixing unsupported claims.

### Phase 5 — Downstream RAG micro-eval

Goal: judge parser changes by answer quality, not by extraction volume alone.

Use 12-doc deterministic micro-queries:

- metadata facts
- requirement/qualification/deliverable facts
- table facts
- page-citation stress
- duplicate-alias stress
- chart/diagram/system-flow facts where present

Metrics:

- retrieval recall@k
- citation precision and page validity
- groundedness/unsupported claim rate
- abstention correctness
- metadata alias correctness
- table/chart/diagram answerability delta

Acceptance:

- A candidate or router improves at least one hard dimension without violating
  page citation or metadata invariants.

### Phase 6 — ADR / canonical integration decision

Only after the 12-doc evidence exists:

- Decide whether to keep PyMuPDF4LLM primary + sidecars, add a route-based parser
  ensemble, or replace any canonical parser path.
- Write/update ADR before changing default ingestion behavior or promoting the
  eval surface as reviewer evidence.
- If evidence is mixed, expand from 12-doc to 96 path-PDF run before ADR.

## Non-goals

- Do not run full-document OCR by default.
- Do not replace PyMuPDF4LLM canonical ingestion in the same slice as harness work.
- Do not treat PaddleOCR and PaddleOCR-VL as equivalent candidates.
- Do not require VLM on every page.
- Do not commit raw parser outputs, raw page text, or hosted payload dumps.

## Suggested implementation order

1. Fix harness OCR options and provenance.
2. Complete 12-doc PyMuPDF4LLM OCR-off + pdfplumber sidecar run.
3. Add page audit/router labels.
4. Add PaddleOCR classic OCR only for `ocr_needed` pages.
5. Add PP-StructureV3/PaddleOCR-VL for `vlm_needed` pages.
6. Add postprocessing merge and downstream micro-eval.
7. Promote decision to ADR only if defaults/eval surface change.

## Validation commands

```bash
python3 -m pytest tests/test_parser_candidate_eval.py -q
python3 -m py_compile scripts/run_parser_candidate_eval.py scripts/summarize_parser_candidate_eval.py
python3 scripts/run_parser_candidate_eval.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-12doc-subset.json \
  --candidates pymupdf4llm_current,pdfplumber_table_sidecar \
  --run-id <run_id>
python3 scripts/summarize_parser_candidate_eval.py --run-id <run_id>
make real-eval-v2-guard
git diff --check
```

## Evidence required before implementation handoff is considered complete

- 12-doc aggregate candidate report.
- Duplicate alias invariant check for rows 17/55 and 23/48.
- Page audit distribution showing how many pages are routed to OCR/VLM.
- At least one table-heavy and one image/chart/diagram-heavy case inspected via
  aggregate-safe metrics.
- Explicit skip reasons for uninstalled or unconfigured candidates.

## Progress — 2026-06-05 Phase 0 smoke run

Run ID: `parser-12doc-ocr-off-smoke-20260605T050845Z`

Command shape:

```bash
python3 scripts/run_parser_candidate_eval.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-12doc-subset.json \
  --candidates pymupdf4llm_current,pdfplumber_table_sidecar \
  --run-id parser-12doc-ocr-off-smoke-20260605T050845Z \
  --no-pymupdf4llm-use-ocr \
  --pymupdf4llm-timeout-s 45 \
  --pdfplumber-max-pages 3
python3 scripts/summarize_parser_candidate_eval.py --run-id parser-12doc-ocr-off-smoke-20260605T050845Z
```

Aggregate result:

| candidate | docs | ok | failed | pages_seen_rate | page_span_coverage | tables | duplicate_alias_ok | runtime_s | failures |
|---|---:|---:|---:|---:|---:|---:|---|---:|---|
| `pymupdf4llm_current` | 12 | 5 | 7 | 0.28 | 0.4167 | 0 | true | 465.0777 | `parse_timeout: 7` |
| `pdfplumber_table_sidecar` | 12 | 12 | 0 | 0.0292 | 1.0 | 48 | true | 3.4712 | `{}` |

Interpretation:

- The OCR-off control no longer invokes document-wide Tesseract, but PyMuPDF4LLM
  still times out on many long/complex 12-doc subset files at a 45s per-document
  budget. Timeout must remain a first-class failure mode in the bake-off.
- `pdfplumber_table_sidecar` is fast for a first-3-page smoke and confirms table
  density without needing full OCR/VLM.
- Duplicate alias invariants passed for both candidates, so path-level metadata
  separation is preserved by the harness.

Next action:

- Add page-audit routing before trying more full-document extraction: text density,
  image density, table density, and VLM-needed labels should decide where OCR/VLM
  runs.
- Keep PyMuPDF4LLM as control, but do not assume it is cheap enough for full-doc
  extraction without timeout/profiling on this subset.

## Progress — 2026-06-05 Phase 1 page-audit routing

Run ID: `page-audit-12doc-20260605T052555Z`

Command shape:

```bash
python3 scripts/audit_parser_pages.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-12doc-subset.json \
  --run-id page-audit-12doc-20260605T052555Z
```

Aggregate route result over the 12-doc subset:

| route | pages |
|---|---:|
| `text_layer` | 213 |
| `table_sidecar` | 831 |
| `ocr_needed` | 34 |
| `vlm_needed` | 154 |

Label counts can overlap by page and are therefore larger than primary route
counts:

| label | pages |
|---|---:|
| `text_layer` | 1115 |
| `table_sidecar` | 895 |
| `ocr_needed` | 117 |
| `vlm_needed` | 154 |

Other aggregate signals:

- Pages audited: 1232 / 1232 subset pages
- Duplicate alias invariant: passed
- Table-bearing pages: 895
- Image signal pages: 1232 (HWP-converted PDFs appear to carry image objects or
  image blocks broadly; use `vlm_needed`, not raw `image_pages`, for VLM routing)
- Average text chars/page: 744.8604

Important per-doc signals:

- Row 62 has the largest VLM-needed route count: 54 pages.
- Row 16 has the largest OCR-needed primary route count: 20 pages.
- Row 95 page audit runtime was high (92.26s), likely from table detection on a
  large/complex PDF; future routing runs should keep table detection profiled or
  allow a table-audit timeout/cap.

Interpretation:

- OCR should remain selective: only 34 pages are primary `ocr_needed`, though 117
  pages carry an OCR label as a secondary signal.
- Tables dominate the subset: 831 pages are primary `table_sidecar`, and 895 pages
  have table labels. Table structure extraction is therefore a core parser surface,
  not an afterthought.
- VLM/document-parser candidates are justified: 154 pages are primary
  `vlm_needed`, especially row 62. This is the correct target for PaddleOCR-VL /
  PP-StructureV3 / hosted document parser evaluation.

Next action:

1. Add candidate execution filters that can run only pages with a target route or
   label, e.g. `--route vlm_needed` or `--label ocr_needed`.
2. Add PaddleOCR classic OCR candidate for OCR-labeled pages.
3. Add PP-StructureV3/PaddleOCR-VL candidate for VLM-labeled pages; keep it
   separate from classic PaddleOCR.
4. Add table-audit timeout/cap before expanding to all 96 path PDFs.

## Progress — 2026-06-05 Phase 2 route-filtered PaddleOCR classic smoke

Run ID: `route-paddleocr-ocr-needed-smoke-20260605T055750Z`

Command shape:

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-12doc-20260605T052555Z/page_audit.json \
  --candidates paddleocr_classic \
  --labels ocr_needed \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 60 \
  --run-id route-paddleocr-ocr-needed-smoke-20260605T055750Z
```

Aggregate result:

| candidate | selected_pages | ok pages | blocks | text chars | avg confidence | runtime_s |
|---|---:|---:|---:|---:|---:|---:|
| `paddleocr_classic` | 1 | 1 | 2 | 36 | 0.9712 | 24.3399 |

Version and model bundle recorded in the aggregate:

```text
paddleocr==3.5.0
paddlex==3.5.2
paddlepaddle==3.3.1
models=PP-LCNet_x1_0_textline_ori, PP-OCRv5_server_det, korean_PP-OCRv5_mobile_rec
```

Page inspected:

- `csv_row=17`, page `8`
- Audit labels: `ocr_needed`, `vlm_needed`
- Audit primary route: `vlm_needed`

Implementation notes:

- Added `scripts/run_route_filtered_candidate_eval.py` so expensive candidates
  can run only on routed pages instead of whole documents.
- Added page-level subprocess timeout via `--page-timeout-s`; a 5-page / 144 DPI
  probe exceeded two minutes on local CPU, so route candidate runs must stay
  timeout-bounded.
- Patched `visual_ingestion.paddleocr_provider` for PaddleOCR 3.x compatibility:
  local `paddleocr==3.5.0` rejects the older `show_log` constructor arg and
  rejects `cls=True` on `.ocr()`. The provider now supports both 2.x result
  shapes and 3.x `OCRResult.json` shapes.

Interpretation:

- PaddleOCR classic is viable as a routed OCR provider, not as a document-wide
  default. On this machine, even one page costs about 24s at 72 DPI because the
  subprocess loads the PP-OCRv5 bundle.
- Keep this candidate as `PaddleOCR classic current bundle`; do not compare
  internal detector/recognizer variants yet. Do internal model ablation only if
  PaddleOCR classic beats or clearly complements Tesseract on a routed sample.
- Next candidate class is still separate: PP-StructureV3 / PaddleOCR-VL for
  `vlm_needed` pages, especially row 62. It should use PaddleOCR 3.6.0 /
  PaddleOCR-VL-1.6 evidence when evaluated.

Next action:

1. Run a tiny Tesseract-vs-PaddleOCR comparison on the same `ocr_needed` page(s)
   or add a Tesseract candidate to the route-filtered runner.
2. Add PP-StructureV3/PaddleOCR-VL candidate discovery for `vlm_needed` pages.
3. Add a table-audit timeout/cap before expanding page audit beyond the 12-doc
   subset.

## Progress — 2026-06-05 Phase 3 Tesseract routed baseline

Run ID: `route-ocr-needed-tesseract-vs-paddleocr-20260605T062703Z`

Command shape:

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-12doc-20260605T052555Z/page_audit.json \
  --candidates paddleocr_classic,tesseract_baseline \
  --labels ocr_needed \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 120 \
  --tesseract-lang kor+eng \
  --run-id route-ocr-needed-tesseract-vs-paddleocr-20260605T062703Z
```

Aggregate result:

| candidate | selected_pages | ok pages | failed pages | blocks | text chars | avg confidence | runtime_s | failures |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `tesseract_baseline` | 1 | 1 | 0 | 3 | 35 | 0.849 | 77.0404 | `{}` |
| `paddleocr_classic` | 1 | 0 | 1 | 0 | 0 | N/A | 121.3859 | `page_inference_failed: 1` |

Tesseract local baseline:

```text
pytesseract==0.3.13
tesseract==5.5.2
requested_lang=kor+eng
available_langs include kor and eng
```

Interpretation:

- Tesseract with explicit `kor+eng` is viable on the same routed OCR page, but
  still expensive at 72 DPI (`75.0379s` page runtime).
- PaddleOCR classic cannot be judged from the comparison run alone: it succeeded
  on the same page in the standalone run (`24.3399s`, 2 blocks, 36 chars,
  confidence `0.9712`) but timed out at 120s in the later paired run. Treat this
  as a runtime stability / warmup / process-isolation problem, not an accuracy
  verdict.
- The route runner now supports both candidates and records page timeouts rather
  than hanging. This is enough for controlled small-N follow-up, but not enough
  for a canonical OCR decision.

Next action:

1. Add warmup/retry policy or candidate order isolation before expanding the OCR
   comparison beyond one page.
2. Add a tiny route-filter run over row 16 OCR-primary pages after timeout/retry
   handling is stable.
3. Start PP-StructureV3/PaddleOCR-VL discovery for `vlm_needed` pages separately
   from classic OCR.

## Progress — 2026-06-05 Phase 4 retry gate

Implementation:

- Added `--page-retries` to `scripts/run_route_filtered_candidate_eval.py`.
- Each page artifact now records an `attempts` list so timeout/retry behavior is
  auditable in raw private output.
- Added a unit regression where the first page attempt raises `TimeoutError` and
  the second attempt succeeds; the document status remains `ok`, and the failed
  attempt is retained in the page artifact.

Validation:

```bash
python3 -m pytest tests/test_route_filtered_candidate_eval.py -q
python3 -m py_compile scripts/run_route_filtered_candidate_eval.py tests/test_route_filtered_candidate_eval.py
ruff check scripts/run_route_filtered_candidate_eval.py tests/test_route_filtered_candidate_eval.py
git diff --check
```

Gate:

- Do not expand routed OCR comparison beyond a tiny sample unless
  `--page-timeout-s` and `--page-retries` are set explicitly in the run command.
- Treat timeout counts as first-class candidate metrics; do not silently drop
  failed attempts.

Next action:

1. Re-run row 16 OCR-primary sample with explicit timeout + retry.
2. Start PP-StructureV3/PaddleOCR-VL setup and docs/version check for
   `vlm_needed` pages.

## Progress — 2026-06-05 Phase 5 row 16 OCR-primary tiny sample

Run ID: `route-row16-ocr-primary-smoke-20260605T064211Z`

Command shape:

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-12doc-20260605T052555Z/page_audit.json \
  --candidates tesseract_baseline,paddleocr_classic \
  --primary-routes ocr_needed \
  --csv-rows 16 \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 45 \
  --page-retries 1 \
  --tesseract-lang kor+eng \
  --run-id route-row16-ocr-primary-smoke-20260605T064211Z
```

Aggregate result over row 16 page 1:

| candidate | selected_pages | ok pages | blocks | text chars | avg confidence | runtime_s | failures |
|---|---:|---:|---:|---:|---:|---:|---|
| `tesseract_baseline` | 1 | 1 | 5 | 54 | 0.8694 | 1.0681 | `{}` |
| `paddleocr_classic` | 1 | 1 | 4 | 40 | 0.9686 | 21.5438 | `{}` |

Interpretation:

- On row 16 page 1, both routed OCR candidates completed within the bounded run.
- Tesseract was much faster on this page, while PaddleOCR reported higher average
  confidence. This is not a quality verdict because no page-level ground truth or
  human review has been attached.
- The row 17 vs row 16 contrast confirms that OCR runtime is page-dependent and
  candidate-dependent; timeout/retry must stay in every expansion command.
- Future Tesseract metadata should store only relevant language availability and
  count, not the full local language list, to keep aggregate reports compact.

Next action:

1. Add page-level qualitative review rubric / mini ground truth for a tiny OCR
   sample before calling either OCR candidate better.
2. Start PP-StructureV3/PaddleOCR-VL candidate setup for `vlm_needed` pages.

## Progress — 2026-06-05 Phase 6 Paddle VLM/structure setup check

Local availability:

```text
paddleocr==3.5.0
classes exposed: PPStructureV3, PaddleOCRVL
PaddleOCRVL signature default: pipeline_version='v1.5'
downloaded VLM/structure models: none found under ~/.paddlex/official_models
```

Local class signatures show the relevant switches:

- `PPStructureV3(..., use_table_recognition, use_formula_recognition,
  use_chart_recognition, use_region_detection, ...)`
- `PaddleOCRVL(..., pipeline_version='v1.5', use_layout_detection,
  use_chart_recognition, use_ocr_for_image_block, ...)`

External latest-state evidence checked on 2026-06-05:

- PyPI `paddleocr` latest is `3.6.0`, released 2026-05-28:
  <https://pypi.org/project/paddleocr/>
- GitHub release `v3.6.0` says it releases the PaddleOCR-VL-1.6 document parsing
  solution and official API SDKs:
  <https://github.com/PaddlePaddle/PaddleOCR/releases/tag/v3.6.0>
- Official PP-StructureV3 docs describe strengthened layout detection, table
  recognition, formula recognition, chart understanding, reading order, and
  Markdown conversion:
  <https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html>
- Official PaddleOCR API Python SDK docs say hosted document parsing defaults to
  `PADDLE_OCR_VL_16` and supports `PP_STRUCTURE_V3`, `PADDLE_OCR_VL`,
  `PADDLE_OCR_VL_15`, and `PADDLE_OCR_VL_16`; the SDK submits jobs to hosted
  services and does not run local inference:
  <https://www.paddleocr.ai/latest/en/version3.x/inference_deployment/serving/paddleocr_official_api/python.html>

Decision:

- Keep `PPStructureV3` and `PaddleOCRVL` as separate `vlm_needed` candidates.
- For local PaddleOCR-VL-1.6, upgrade/evaluate in an isolated optional env or
  explicit dependency lane because local `3.5.0` defaults to VL 1.5.
- Hosted official API is a separate opt-in candidate and needs credentials /
  endpoint configuration; it should use page-selected payloads only and record
  `model=PaddleOCR-VL-1.6` or `model=PP-StructureV3`.
- Do not run local PP-StructureV3/PaddleOCRVL over full documents. First smoke
  should be one `vlm_needed` page from row 62 with timeout/retry and model-cache
  provenance.

Next action:

1. Add `vlm_needed` route candidate skeletons with explicit skip reasons:
   `pp_structurev3_local`, `paddleocr_vl_local`, and optionally
   `paddleocr_official_api`.
2. Run only dry-run/skipped candidate coverage until the isolated env/API key
   choice is explicit.

## Progress — 2026-06-05 Phase 7 VLM skeleton coverage

Run ID: `route-row62-vlm-skeleton-20260605T064649Z`

Command shape:

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-12doc-20260605T052555Z/page_audit.json \
  --candidates pp_structurev3_local,paddleocr_vl_local,paddleocr_official_api \
  --primary-routes vlm_needed \
  --csv-rows 62 \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 45 \
  --page-retries 0 \
  --run-id route-row62-vlm-skeleton-20260605T064649Z
```

Selected page:

- Row 62 has 54 primary `vlm_needed` pages.
- The skeleton run selected row 62 page 1 (`text_layer` + `vlm_needed`,
  primary `vlm_needed`, 83 text chars, 6 images).

Aggregate result:

| candidate | status | selected_pages | failure |
|---|---|---:|---|
| `pp_structurev3_local` | skipped | 1 | `candidate_not_enabled` |
| `paddleocr_vl_local` | skipped | 1 | `candidate_not_enabled` |
| `paddleocr_official_api` | skipped | 1 | `candidate_not_enabled` |

Version/availability notes:

- `pp_structurev3_local`: class available in local `paddleocr==3.5.0`, but no
  VLM/structure models cached; inference intentionally disabled.
- `paddleocr_vl_local`: class available in local `paddleocr==3.5.0`, but local
  signature defaults to VL 1.5; inference intentionally disabled until isolated
  env / model-cache choice.
- `paddleocr_official_api`: `PaddleOCRClient` class is not available in local
  `paddleocr==3.5.0`; use package 3.6.0+ and credentials if this lane is chosen.

Decision:

- Skeleton coverage is complete: reviewer-visible reports now show that
  `vlm_needed` candidates are considered but intentionally blocked from heavy
  inference.
- Next implementation choice is material: local isolated env/model cache vs
  hosted official API credentials. Do not silently start either as part of
  ordinary runner expansion.

## Progress — 2026-06-05 Phase 8 local-vs-hosted VLM/API smoke

User instruction: run both local and hosted paths as far as they can safely go.

Implementation updates:

- Added `--enable-local-vlm`, `--allow-model-download`, `--local-vlm-device`,
  and `--paddleocr-python` to `scripts/run_route_filtered_candidate_eval.py`.
  This lets local PP-StructureV3/PaddleOCR-VL run from an isolated Python env
  instead of mutating the repo/global RAG environment.
- Added `--enable-hosted-api`, `--paddleocr-api-model`, request/poll timeout,
  and base-url flags for the hosted PaddleOCR official API candidate. The runner
  records `PADDLEOCR_ACCESS_TOKEN` presence but never writes the token.
- Added skip/preflight gates:
  - local VLM candidates require `--enable-local-vlm`;
  - local model downloads require `--allow-model-download`;
  - hosted API calls require `--enable-hosted-api` and `PADDLEOCR_ACCESS_TOKEN`;
  - aggregate reports still omit raw OCR/VLM text.
- Added regression coverage for local model-cache skip and hosted credential skip.

Isolated env created outside the repo:

```text
~/.cache/bidmate-docagent/paddleocr-vl-venv-py311
paddleocr==3.6.0
paddlex==3.6.1
paddlepaddle==3.3.1
PyMuPDF==1.27.2.3
```

Latest SDK/API availability in that env:

- `PPStructureV3`: available
- `PaddleOCRVL`: available, default `pipeline_version='v1.6'`
- `PaddleOCRClient`: available
- `PPStructureV3Options` / `PaddleOCRVLOptions`: available

Runs:

| run_id | candidate | selected | result | evidence |
|---|---|---:|---|---|
| `route-row62-vlm-local-and-api-preflight-20260605T070049Z` | `pp_structurev3_local`, `paddleocr_vl_local` | 1 | skipped | `model_cache_missing` under current local 3.5.0 env |
| `route-row62-vlm-local-and-api-preflight-20260605T070049Z` | `paddleocr_official_api` | 1 | skipped | `credential_unavailable` |
| `route-row62-ppstructurev3-local-download-smoke-20260605T070125Z` | `pp_structurev3_local` | 1 | failed | global env lacks `paddlex[ocr]` extra |
| `route-row62-local-vlm-and-api-venv-smoke-20260605T071228Z` | `pp_structurev3_local` | 1 | failed | isolated 3.6 env could run dependencies, but model download from default/BOS source failed |
| `route-row62-ppstructurev3-local-hf-smoke-20260605T071607Z` | `pp_structurev3_local` | 1 | failed | HuggingFace-forced model source downloaded layout/OCR models, then CPU page inference timed out at 420s |
| `route-row62-paddleocrvl-api-venv-preflight-20260605T072334Z` | `paddleocr_vl_local` | 1 | skipped | VL model cache still missing; heavy VL model download not started |
| `route-row62-paddleocrvl-api-venv-preflight-20260605T072334Z` | `paddleocr_official_api` | 1 | skipped | `PaddleOCRClient` exists in 3.6 env, but token is absent |

Local model cache after the HuggingFace-forced PP-StructureV3 attempt includes:

```text
PP-DocBlockLayout
PP-DocLayout_plus-L
PP-LCNet_x1_0_doc_ori
PP-LCNet_x1_0_table_cls
PP-LCNet_x1_0_textline_ori
PP-OCRv5_server_det
PP-OCRv5_server_rec
UVDoc
korean_PP-OCRv5_mobile_rec
```

Interpretation:

- Hosted API path is implementation-ready in the harness but cannot run without
  `PADDLEOCR_ACCESS_TOKEN`. It is likely paid/quota-bound, so keep it explicit
  and page-selected.
- Local PP-StructureV3 on Apple/CPU is not a practical default from this smoke:
  even after successful dependency isolation and partial model download, row 62
  page 1 timed out at 420s.
- Local PaddleOCR-VL-1.6 should not be downloaded/run blindly next. It is likely
  heavier than PP-StructureV3; keep it behind explicit cache/download controls or
  evaluate via hosted API / remote GPU if a credential or compute budget is chosen.
- The current practical path remains: text-layer PyMuPDF4LLM + table sidecars +
  routed classic OCR first; VLM/document-parser candidates stay opt-in for a tiny
  chart/diagram sample.

Next action:

1. Add OCR qualitative review/mini ground-truth for row 16 page 1 and row 17 page
   8 before claiming OCR quality.
2. Add a table-audit timeout/cap before expanding any 96-path audit.
3. If VLM is still needed, prefer hosted API on 1–2 selected pages once a token /
   quota is intentionally configured; otherwise use a remote/GPU local lane rather
   than Apple CPU PP-StructureV3.

## Progress — 2026-06-05 Phase 9 OCR mini review packet

Goal: stop comparing OCR candidates by confidence/length alone and create a tiny
page-level review surface with image evidence, raw OCR text, and explicit draft
truth fields.

Implementation:

- Added `scripts/build_ocr_review_packet.py`.
- Added `tests/test_ocr_review_packet.py`.
- The script groups route-filtered OCR artifacts by `(csv_row, page)`, renders
  page PNGs, writes raw OCR text only to the private packet, and writes a
  textless aggregate report for reviewer-safe status/count evidence.

Run ID: `ocr-mini-review-row16-row17-20260605T074054Z`

Artifacts:

- Private packet: `data/private/real100_v2/ocr_review/ocr-mini-review-row16-row17-20260605T074054Z/review_packet.md`
- Private JSON: `data/private/real100_v2/ocr_review/ocr-mini-review-row16-row17-20260605T074054Z/review_packet.json`
- Rendered page images:
  - `data/private/real100_v2/ocr_review/ocr-mini-review-row16-row17-20260605T074054Z/images/row-0016-page-0001.png`
  - `data/private/real100_v2/ocr_review/ocr-mini-review-row16-row17-20260605T074054Z/images/row-0017-page-0008.png`
- Textless aggregate: `reports/parser_candidate_eval/ocr-mini-review-row16-row17-20260605T074054Z/ocr_review.md`

Reviewed pages:

| csv_row | page | route | candidates | draft winner |
|---:|---:|---|---|---|
| 16 | 1 | `ocr_needed` | `tesseract_baseline`, `paddleocr_classic` | `paddleocr_classic` |
| 17 | 8 | `vlm_needed` + `ocr_needed` | `tesseract_baseline`, `paddleocr_classic` | `paddleocr_classic` |

Draft visual-review findings:

- Row 16 page 1: PaddleOCR captures the core title/document type better than
  Tesseract, though it needs normalization for `(CMS) 고도화` spacing and
  `K-water`. Tesseract is fast but corrupts CMS and issuer text.
- Row 17 page 8: PaddleOCR captures the full schedule-change sentence and page
  number; Tesseract only recovers fragments, so it is not adequate for
  citation-bearing evidence on this page.
- These are `draft_ai_visual_review` notes, not human-confirmed benchmark truth.

Decision:

- Do not promote a corpus-level OCR winner yet, but routed PaddleOCR is the
  stronger candidate on these two inspected pages.
- Next compare more pages only after adding table-audit caps and a small
  human-reviewable ground-truth set. Keep all quality claims scoped to the review
  packet/run id.

## Progress — 2026-06-05 Phase 10 table-audit timeout/cap

Goal: make page audit safe to expand beyond tiny samples by preventing
`find_tables()` from dominating runtime.

Implementation:

- Added `--table-timeout-s` to `scripts/audit_parser_pages.py` for optional
  per-page PyMuPDF `find_tables()` timeout.
- Added `--table-max-pages-per-doc` so table detection can be limited to early
  pages while text/image/OCR/VLM routing features still cover every audited page.
- Added `--disable-table-detection` for fast routing runs that only need
  text/image/OCR/VLM labels.
- Added regression tests for timeout and cap behavior in
  `tests/test_parser_page_audit.py`.

Smoke run:

```bash
python3 scripts/audit_parser_pages.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-12doc-subset.json \
  --table-timeout-s 2 \
  --table-max-pages-per-doc 3 \
  --run-id page-audit-12doc-table-capped-20260605T074646Z
```

Result:

- Pages audited: `1232/1232`
- Runtime: `24.1s` wall clock for command
- Route counts: `ocr_needed=34`, `table_sidecar=11`, `text_layer=1033`,
  `vlm_needed=154`
- Duplicate alias invariant: passed
- Warning count: `pymupdf_find_tables_skipped_by_cap=1196`
- Slowest docs after cap: row 23 `3.87s`, row 36 `3.21s`, row 95 `3.16s`

Interpretation:

- The cap makes full-page text/image/VLM routing feasible while keeping table
  detection bounded.
- The capped run is not a full table-sidecar measurement because pages after the
  cap intentionally have unknown table counts. Use it for routing expansion; use
  targeted table-sidecar runs for table quality/coverage.
- For 96 path-level PDFs, recommended first expansion shape is
  `--table-timeout-s 2 --table-max-pages-per-doc 3`; if routing-only speed is
  needed, use `--disable-table-detection` and keep table evaluation separate.

Next action:

1. Run 96-path capped page audit if needed for corpus-wide routing counts.
2. Then build a parser output merge schema/element stream plan before wiring OCR
   or table sidecars into canonical RAG chunks.

## Progress — 2026-06-05 Phase 11 96-path capped routing audit

Goal: use the new table-audit cap to get corpus-wide routing counts across all
path-level PDFs without reintroducing full `find_tables()` latency.

Subset artifact:

- `.omx/context/pdf-parser-96path-subset.json` — 96 path-level PDF rows from
  `data/private/real100_v2/converted_pdfs_by_path/manifest.json`.

Command:

```bash
python3 scripts/audit_parser_pages.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-96path-subset.json \
  --table-timeout-s 2 \
  --table-max-pages-per-doc 3 \
  --run-id page-audit-96path-table-capped-20260605T074915Z
```

Artifacts:

- Raw/private audit: `data/private/real100_v2/parser_page_audit/page-audit-96path-table-capped-20260605T074915Z/page_audit.json`
- Aggregate: `reports/parser_candidate_eval/page-audit-96path-table-capped-20260605T074915Z/page_audit.md`

Result:

- Documents: `96`
- Pages audited: `9107`
- Route counts: `text_layer=7807`, `vlm_needed=1029`, `ocr_needed=176`,
  `table_sidecar=92`, `manual_review=3`
- Overlapping labels: `text_layer=8447`, `vlm_needed=1029`, `ocr_needed=657`,
  `table_sidecar=138`, `manual_review=3`
- Image pages: `9030/9107`
- Duplicate alias invariant: passed for row pairs `23/48` and `17/55`
- Expected warning: `pymupdf_find_tables_skipped_by_cap=8819`

Top routed targets:

- VLM-heavy rows: row 62 (`54` VLM pages), row 91 (`29`), row 71 (`27`),
  row 84 (`26`), row 27 (`25`).
- OCR-heavy rows: row 16 (`20` OCR pages), row 83 (`11`), row 96 (`9`),
  row 42 (`8`), row 43 (`8`).
- Slowest docs after cap are still small enough for expansion: row 36 `4.10s`,
  row 35 `3.51s`, row 95 `3.20s`.

Decision:

- Corpus-wide routing can now proceed from capped page audit evidence.
- Table-sidecar counts in this run are intentionally conservative because only
  first 3 pages/doc ran `find_tables()`. Do not use this run as table coverage
  truth; use targeted table eval for table quality.
- Next implementation should define a merge/element schema before canonical RAG
  chunking consumes OCR/table/VLM outputs.

## Progress — 2026-06-05 Phase 12 merge schema contract

Created merge/element-stream contract:

- `docs/plans/T-2026-0081-parser-output-merge-schema.md`

Key decisions:

- Path aliases remain separate documents even when `source_sha256` matches.
- Metadata is RAG data and can become `metadata_fact` elements.
- `text_layer` remains the citation backbone.
- Table/OCR/VLM outputs are additive sidecars until eval/ADR promotes a default.
- VLM `figure`/`chart`/`diagram` summaries are non-citation-ready by default.
- OCR does not overwrite text-layer text; it only augments routed/low-text pages.

Next action:

1. Implement a 12-doc element-stream builder behind a new script, not canonical
   ingestion.
2. Use the builder to produce a local/private element artifact for metadata +
   text control + table sidecar + reviewed OCR sample.
3. Run tiny RAG micro-eval only after the element stream exists.

## Progress — 2026-06-05 Phase 13 parser element stream harness

Goal: materialize the merge schema as a harness-only artifact before any
canonical ingestion/chunking change.

Added:

- `scripts/build_parser_element_stream.py`
- `tests/test_parser_element_stream.py`

Contract enforced by the script/test:

- Path-level rows remain separate documents.
- CSV/header metadata becomes `metadata_fact` elements because metadata is RAG
  data.
- PyMuPDF4LLM text output is retained as `text_layer` / `control` elements.
- pdfplumber table output is additive `table` / `sidecar` output.
- Reviewed OCR winners become additive `ocr_text` / `routed_ocr` elements.
- Private raw text is written only under `data/private/real100_v2/`; aggregate
  reports omit raw text.

Command:

```bash
python3 scripts/build_parser_element_stream.py \
  --run-id parser-element-stream-12doc-20260605T075908Z
```

Artifacts:

- Private stream: `data/private/real100_v2/parser_element_stream/parser-element-stream-12doc-20260605T075908Z/element_stream.json`
- Aggregate: `reports/parser_candidate_eval/parser-element-stream-12doc-20260605T075908Z/element_stream.md`

Result:

- Documents: `12`
- Elements: `562`
- Element types: `metadata_fact=167`, `text_layer=345`, `table=48`,
  `ocr_text=2`
- Source roles: `metadata=167`, `control=345`, `sidecar=48`, `routed_ocr=2`
- Citation-ready count in this harness: `562/562`

Interpretation:

- The merge contract is now executable and reviewable without changing
  canonical ingestion.
- Some 12-doc rows have no `text_layer` elements because the earlier
  PyMuPDF4LLM candidate timed out on those PDFs; table/OCR sidecars still attach
  where available.
- Next RAG-facing work should be a micro-eval/index experiment over this element
  stream, not a direct replacement of `ingestion.py`.

Next action:

1. Add an eval-only chunk/index adapter for `parser_element_stream`.
2. Run a tiny retrieval smoke over metadata/table/OCR facts.
3. Only after retrieval evidence, decide whether an ADR is needed to promote any
   part of this harness into canonical ingestion.

## Progress — 2026-06-05 Phase 14 element-stream retrieval smoke

Goal: prove the element stream can feed the existing retrieval stack through an
eval-only adapter before changing canonical ingestion.

Added:

- `scripts/run_parser_element_stream_retrieval_smoke.py`
- `tests/test_parser_element_stream_retrieval_smoke.py`

Command:

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --run-id parser-element-retrieval-smoke-12doc-20260605T080534Z
```

Artifacts:

- Private hashing index: `data/private/real100_v2/parser_element_retrieval_smoke/parser-element-retrieval-smoke-12doc-20260605T080534Z/index/index.json`
- Textless aggregate: `reports/parser_candidate_eval/parser-element-retrieval-smoke-12doc-20260605T080534Z/retrieval_smoke.md`

Result:

- Documents: `12`
- Chunks: `564` from `562` elements; two long text-layer elements split under
  section chunking.
- Smoke queries: `3/3` passed.
- Element-type chunk counts: `metadata_fact=167`, `text_layer=347`, `table=48`,
  `ocr_text=2`.

Smoke coverage:

- Metadata/project retrieval for row `16` passes.
- Routed OCR cover-page retrieval for row `16` passes; top hit is `ocr_text`.
- Table-sidecar/project retrieval for duplicate-alias rows `23/48` passes; top
  hit is `table` on row `23`.

Decision:

- The element stream can be indexed and retrieved via existing hashing + hybrid
  retrieval without a canonical ingestion change.
- This is a smoke only, not a benchmark: it proves wiring and a few intended
  fact classes, not recall/precision lift.

Next action:

1. Define a small expected-fact set for the 12-doc subset, separated by element
   source (`metadata_fact`, `table`, `ocr_text`, `text_layer`, future `vlm_*`).
2. Turn the current smoke into a scored micro-eval over that expected-fact set.
3. Use the micro-eval to decide whether OCR/table sidecars deserve a canonical
   parser ADR or remain eval-only.

## Progress — 2026-06-05 Phase 15 12-doc expected-fact micro-eval

Goal: convert the wiring smoke into a tiny scored expected-fact eval by element
source.

Added/updated:

- `data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json`
- `scripts/run_parser_element_stream_retrieval_smoke.py` now reports top-1 row
  hits, MRR, and grouped metrics by expected element type/source.

Command:

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --queries-json data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json \
  --run-id parser-element-micro-eval-12doc-20260605T080937Z \
  --top-k 6
```

Artifacts:

- Private hashing index: `data/private/real100_v2/parser_element_retrieval_smoke/parser-element-micro-eval-12doc-20260605T080937Z/index/index.json`
- Textless aggregate: `reports/parser_candidate_eval/parser-element-micro-eval-12doc-20260605T080937Z/retrieval_smoke.md`

Result:

- Expected facts: `6`
- Passed@6: `6/6`
- Top-1 row hits: `5/6`
- MRR: `0.8889`
- By source: metadata `2/2`, OCR `2/2`, table `1/1`, text-layer `1/1`.

Notable miss shape:

- `text_row48_compliance_table` passed within top-6 but expected row `48` ranked
  `3`; rows `80`/`80` outranked it for the compliance-table query. Treat this
  as the next retrieval-tuning case, not a parser failure.

Decision:

- Metadata and routed OCR sidecars are immediately useful in this subset.
- Table sidecar is retrievable for the row 23/48 duplicate-alias project fact.
- Text-layer retrieval still has cross-document term collision; improvement
  should target query/metadata balancing or expected-fact scoring before any
  parser promotion ADR.

Next action:

1. Expand expected facts to include VLM-needed pages once a hosted/API or remote
   GPU lane is available.
2. Add duplicate-alias scoring policy (`source_sha256` siblings vs path-level
   row ids) before using this micro-eval as reviewer evidence.
3. Do not promote OCR/table defaults until the micro-eval is stable and reviewed
   as a measurement surface.

## Progress — 2026-06-05 Phase 16 duplicate-alias scoring policy

Goal: avoid hiding path-level alias/copy behavior in the micro-eval score.

Policy implemented:

- Default scoring is path-row strict: `expected_rows` must match retrieved
  `csv_row`.
- A fact may opt into SHA sibling credit with
  `allow_source_sha256_alias: true`.
- When alias credit is enabled, the runner expands declared rows to all rows in
  the index with the same `source_sha256`, and reports both declared and
  effective rows plus `alias_rows`.
- OCR-specific facts stay path-row strict unless OCR was actually reviewed for
  the alias row.

Updated:

- `data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json`
- `scripts/run_parser_element_stream_retrieval_smoke.py`
- `tests/test_parser_element_stream_retrieval_smoke.py`

Command:

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --queries-json data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json \
  --run-id parser-element-micro-eval-12doc-alias-aware-20260605T081316Z \
  --top-k 6
```

Artifacts:

- Private hashing index: `data/private/real100_v2/parser_element_retrieval_smoke/parser-element-micro-eval-12doc-alias-aware-20260605T081316Z/index/index.json`
- Textless aggregate: `reports/parser_candidate_eval/parser-element-micro-eval-12doc-alias-aware-20260605T081316Z/retrieval_smoke.md`

Result:

- Expected facts: `6`
- Passed@6: `6/6`
- Top-1 row hits: `5/6`
- MRR: `0.8889`
- Alias expansions: row `17` effective rows `[17,55]`; row `23` effective
  rows `[23,48]`.
- OCR row `17` remains strict because only row 17/page 8 was OCR-reviewed.

Decision:

- The micro-eval now has an explicit duplicate-alias scoring contract.
- It is still a tiny candidate measurement surface, not canonical benchmark
  evidence.

## Progress — 2026-06-05 Phase 17 VLM/API row 62 blocker samples

Goal: move from parser/table/OCR micro-eval into the VLM/API lane without
spending API money or hiding local CPU feasibility limits.

Target page:

- `csv_row=62`, first primary `vlm_needed` page from
  `page-audit-96path-table-capped-20260605T074915Z`.

Runs:

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-96path-table-capped-20260605T074915Z/page_audit.json \
  --candidates paddleocr_official_api \
  --primary-routes vlm_needed \
  --csv-rows 62 \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 60 \
  --page-retries 0 \
  --enable-hosted-api \
  --paddleocr-python ~/.cache/bidmate-docagent/paddleocr-vl-venv-py311/bin/python \
  --run-id route-row62-hosted-api-preflight-20260605T083248Z
```

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-96path-table-capped-20260605T074915Z/page_audit.json \
  --candidates paddleocr_vl_local \
  --primary-routes vlm_needed \
  --csv-rows 62 \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 60 \
  --page-retries 0 \
  --enable-local-vlm \
  --paddleocr-python ~/.cache/bidmate-docagent/paddleocr-vl-venv-py311/bin/python \
  --run-id route-row62-paddleocr-vl-preflight-20260605T083248Z
```

```bash
python3 scripts/run_route_filtered_candidate_eval.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-96path-table-capped-20260605T074915Z/page_audit.json \
  --candidates pp_structurev3_local \
  --primary-routes vlm_needed \
  --csv-rows 62 \
  --max-pages 1 \
  --render-dpi 72 \
  --page-timeout-s 120 \
  --page-retries 0 \
  --enable-local-vlm \
  --local-vlm-device cpu \
  --paddleocr-python ~/.cache/bidmate-docagent/paddleocr-vl-venv-py311/bin/python \
  --run-id route-row62-ppstructurev3-local-sample-20260605T083331Z
```

Artifacts:

- `reports/parser_candidate_eval/route-row62-hosted-api-preflight-20260605T083248Z/route_candidate_eval.md`
- `reports/parser_candidate_eval/route-row62-paddleocr-vl-preflight-20260605T083248Z/route_candidate_eval.md`
- `reports/parser_candidate_eval/route-row62-ppstructurev3-local-sample-20260605T083331Z/route_candidate_eval.md`

Result:

- Hosted API SDK is available in the isolated PaddleOCR 3.6 env, but
  `PADDLEOCR_ACCESS_TOKEN` is not configured. The run skipped with
  `credential_unavailable`, so no hosted/paid call was made.
- Local `PaddleOCRVL` class is available (`paddleocr==3.6.0`, default v1.6), but
  the required VL model cache is missing. The run skipped with
  `model_cache_missing`; no heavy VL model download was started.
- Local `PPStructureV3` class is available and some layout/OCR models are
  cached, but row 62 page 1 failed under a 120s page timeout on CPU
  (`page_inference_failed`, page runtime `120.287s`, doc runtime `133.8847s`).

Decision:

- Local CPU PP-StructureV3 is not viable as the default VLM route for this repo.
- PaddleOCR-VL local cannot produce a sample without a deliberate heavy model
  download and likely non-CPU execution plan.
- Hosted API is the cleanest next VLM sample lane, but it requires an access
  token and may incur provider cost; keep it opt-in and one-page bounded.

## Progress — 2026-06-05 Phase 18 Paddle hosted API signup blocker

New constraint from maintainer:

- `PADDLEOCR_ACCESS_TOKEN` acquisition is blocked because Baidu AI Studio / PaddleOCR
  official API signup requires a mainland China phone number.

Decision:

- Do not spend more time pursuing PaddleOCR hosted API credentials for this repo.
- Keep `paddleocr_official_api` as a harness candidate only for environments that
  already have a token, but remove it from the recommended next VLM sample lane.
- The next VLM/API sample should pivot to a non-China-access-gated provider.

Replacement candidate lanes:

1. Upstage Document Parse API — document-parser-shaped API with layout/table/chart
   output; likely the closest hosted replacement for PaddleOCR-VL/PP-Structure.
2. OpenAI PDF/file-input vision sample — good for one-page chart/diagram
   description and RAG-sidecar summaries, but should be evaluated as VLM
   annotation, not a deterministic OCR/table parser.
3. Google Document AI Gemini Layout Parser — strong RAG/layout-parser candidate,
   but requires GCP setup and paid processor configuration.

Next action:

- Add a provider-neutral VLM/API candidate interface before wiring any one vendor
  into the runner.
- First concrete sample should be one row 62 `vlm_needed` page with whichever
  non-China-access-gated credential is available locally.

## Progress — 2026-06-05 Phase 19 hosted API skipped

Maintainer decision:

- Hosted/paid document intelligence APIs are skipped for now.
- This applies to PaddleOCR hosted API, Upstage Document Parse, and similar paid
  hosted parse/VLM lanes unless explicitly re-enabled later.

Reason:

- PaddleOCR official API token acquisition is access-gated.
- Upstage pricing is too expensive for the current corpus shape, especially for
  route-wide or full-corpus page counts.

Decision:

- Do not implement or run hosted API candidate calls in the next parser/VLM
  phase.
- Keep existing hosted API skeletons as disabled harness code only; they must
  remain opt-in and credential-gated.
- Continue with local/offline paths:
  1. Strengthen text-layer + table sidecar + routed OCR, because these already
     produced retrievable RAG elements.
  2. Treat `vlm_needed` pages as unresolved visual sidecar backlog, not as a
     blocker for the ingestion path.
  3. Add local visual inventory / image-block extraction before considering any
     heavy open-source VLM model download.
  4. Use manual review packets for a tiny set of chart/diagram-heavy pages when
     visual semantics are needed.

Next local-only action:

- Build a `vlm_needed` page inventory packet for top rows (row 62 first), with
  page thumbnails, image counts, text length, table labels, and OCR availability.
- No hosted API call, no paid dependency, no credential requirement.

## Progress — 2026-06-05 Phase 20 local visual inventory row 62

Goal: replace paid/hosted VLM sampling with a local visual inventory packet for
high-priority `vlm_needed` pages.

Added:

- `scripts/build_visual_inventory_packet.py`
- `tests/test_visual_inventory_packet.py`

Command:

```bash
python3 scripts/build_visual_inventory_packet.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-96path-table-capped-20260605T074915Z/page_audit.json \
  --csv-rows 62 \
  --primary-routes vlm_needed \
  --max-pages 12 \
  --render-dpi 72 \
  --run-id visual-inventory-row62-vlm-top12-v2-20260605T091940Z
```

Artifacts:

- Private packet with local thumbnails:
  `data/private/real100_v2/visual_inventory/visual-inventory-row62-vlm-top12-v2-20260605T091940Z/visual_inventory.md`
- Text/image-body-free aggregate:
  `reports/parser_candidate_eval/visual-inventory-row62-vlm-top12-v2-20260605T091940Z/visual_inventory.md`

Result:

- Pages: `12`
- Labels: `vlm_needed=12`, `ocr_needed=6`, `text_layer=6`
- Visual tags: `image_rich=12`, `large_image_area=4`,
  `scanned_form_or_fullpage_image=4`, `low_area_multi_image=8`,
  `ocr_overlap=6`, `table_unknown=11`.

Spot-check observation:

- High-priority pages 166-168 are scanned form/seal-like pages with low text and
  large image area; OCR/manual form review is more likely useful than a generic
  hosted VLM call.
- Page 1 is a cover page; it was flagged by image count because of logos/header
  graphics, not because it has chart/diagram semantics.

Decision:

- The current `image_count >= 4 and text < 300` VLM rule over-routes logo/header
  pages.
- Next local-only improvement is to require a minimum image-area ratio for the
  image-count VLM branch, then rerun capped routing counts.

## Progress — 2026-06-05 Phase 21 VLM routing v2 threshold

Goal: reduce local VLM false positives caused by logos/header graphics after the
row 62 visual inventory showed `low_area_multi_image` pages.

Change:

- Added `--vlm-image-count-min-area-ratio` to `scripts/audit_parser_pages.py`.
- Default: `0.05`.
- The image-count branch now requires:
  `image_count >= 4`, `text_chars < 300`, and `image_area_ratio >= 0.05`.
- Large image area branch remains unchanged at `image_area_ratio >= 0.20`.

Regression test:

- `tests/test_parser_page_audit.py::test_image_count_needs_min_area_for_vlm_route`
  ensures logo/header-like low-area multi-image pages stay `text_layer` instead
  of `vlm_needed`.

Reruns:

```bash
python3 scripts/audit_parser_pages.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-row62-subset.json \
  --table-timeout-s 2 \
  --table-max-pages-per-doc 3 \
  --run-id page-audit-row62-routing-v2-20260605T092124Z
```

```bash
python3 scripts/audit_parser_pages.py \
  --manifest data/private/real100_v2/converted_pdfs_by_path/manifest.json \
  --subset .omx/context/pdf-parser-96path-subset.json \
  --table-timeout-s 2 \
  --table-max-pages-per-doc 3 \
  --run-id page-audit-96path-routing-v2-20260605T092124Z
```

Results:

- Row 62 primary `vlm_needed`: `54 -> 4`.
- 96-path primary `vlm_needed`: `1029 -> 227` (`-802`).
- 96-path primary routes after v2: `text_layer=8249`, `ocr_needed=504`,
  `vlm_needed=227`, `table_sidecar=124`, `manual_review=3`.
- Overlapping label counts after v2: `text_layer=8447`, `ocr_needed=657`,
  `vlm_needed=227`, `table_sidecar=138`, `manual_review=3`.
- Duplicate alias invariant still passed.

Final row62 v2 inventory:

```bash
python3 scripts/build_visual_inventory_packet.py \
  --page-audit data/private/real100_v2/parser_page_audit/page-audit-row62-routing-v2-20260605T092124Z/page_audit.json \
  --csv-rows 62 \
  --primary-routes vlm_needed \
  --max-pages 12 \
  --render-dpi 72 \
  --run-id visual-inventory-row62-vlm-v2-final-20260605T092302Z
```

- Final row62 VLM inventory pages: `4` (`152`, `166`, `167`, `168`).
- All four are low-text, large-image-area, scanned-form/fullpage-image pages
  with OCR overlap.

Decision:

- The practical local path is not generic VLM-first. It is:
  `text_layer` by default, `table_sidecar` when table-detected, routed OCR for
  low-text image/form pages, and a much smaller visual/manual backlog for true
  large-image pages.

## Progress — 2026-06-05 Phase 22 downstream artifacts on routing v2

Goal: make downstream parser element artifacts consume the improved routing v2
page audit.

Updated defaults:

- `scripts/build_parser_element_stream.py` now points to
  `page-audit-96path-routing-v2-20260605T092124Z`.
- `scripts/build_visual_inventory_packet.py` now points to
  `page-audit-96path-routing-v2-20260605T092124Z`.
- `scripts/run_parser_element_stream_retrieval_smoke.py` now points to the
  routing-v2 element stream artifact.

Regenerated:

```bash
python3 scripts/build_parser_element_stream.py \
  --run-id parser-element-stream-12doc-routing-v2-20260605T092518Z
```

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --element-stream data/private/real100_v2/parser_element_stream/parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json \
  --queries-json data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json \
  --run-id parser-element-micro-eval-12doc-routing-v2-20260605T092526Z \
  --top-k 6
```

Results:

- Element stream: `12` docs, `562` elements (`metadata_fact=167`,
  `text_layer=345`, `table=48`, `ocr_text=2`).
- Retrieval micro-eval: `6/6` passed@6, Top-1 row hits `5/6`, MRR `0.8889`.
- Metrics are unchanged from the previous micro-eval because routing labels
  changed, not the underlying metadata/text/table/OCR elements.

Decision:

- Routing v2 is now the default local page-audit surface for this harness.
- Remaining issue is retrieval ranking for `text_row48_compliance_table` (row 48
  rank 3), not parser/VLM routing.

## Progress — 2026-06-05 Phase 23 expected-fact disambiguation

Goal: separate parser/routing failures from micro-eval query ambiguity before
doing retrieval tuning.

Updated:

- `data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json`
- The `text_row48_compliance_table` query now includes row-48-specific project
  terms instead of only generic compliance-table wording.
- The query keeps `allow_source_sha256_alias: true` because rows `23` and `48`
  are path aliases for the same source bytes.

Rerun:

```bash
python3 scripts/run_parser_element_stream_retrieval_smoke.py \
  --element-stream data/private/real100_v2/parser_element_stream/parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json \
  --queries-json data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json \
  --run-id parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z \
  --top-k 6
```

Result:

- Retrieval micro-eval: `6/6` same-hit passed@6.
- Top-1 row hits: `6/6`.
- Top-1 same-hit matches: `5/6`.
- Same-hit MRR: `0.875`.
- Element type chunks: `metadata_fact=167`, `text_layer=347`, `table=48`,
  `ocr_text=2`.

Decision:

- The previous row-48 rank miss was an expected-fact/query ambiguity: generic
  compliance-table wording appears across multiple RFPs.
- No parser/VLM/API change is indicated by that miss.
- Next local-only step should promote this from harness wiring toward an
  ADR/reviewer candidate surface only after documenting query-writing rules,
  duplicate-alias scoring, and aggregate-only evidence boundaries.

## Progress — 2026-06-05 Phase 24 micro-eval surface hardening

Goal: make the 12-doc parser element retrieval smoke harder to misuse as a
benchmark claim.

Updated:

- `scripts/run_parser_element_stream_retrieval_smoke.py`
- `tests/test_parser_element_stream_retrieval_smoke.py`
- `docs/plans/T-2026-0081-parser-output-merge-schema.md`

Rules now documented:

1. Scored micro-eval queries must declare `expected_rows` and
   `expected_element_types`.
2. Boilerplate-only RFP table/checklist wording is insufficient; include
   project/agency/title disambiguators when wording repeats across documents.
3. Duplicate path aliases remain row-strict by default; source-sha alias scoring
   is explicit opt-in and reports declared/effective/alias rows separately.
4. Aggregate reports remain textless: query names and hashes only, no raw query
   text or chunk text.
5. Passing this harness is wiring/query-coverage evidence, not a default-change
   claim.

Regression guard:

- Query config validation rejects duplicate query names, missing
  `expected_rows`, missing `expected_element_types`, non-positive rows, and
  non-boolean `allow_source_sha256_alias`.

Decision:

- The harness is now safer as a reviewer candidate artifact, but still not an
  ADR-approved measurement surface or canonical ingestion gate.

## Progress — 2026-06-05 Phase 25 candidate surface v0 gate

Goal: add an explicit go/no-go gate for treating the 12-doc parser element
retrieval smoke as a candidate reviewer surface.

Added:

- `scripts/validate_parser_element_micro_eval_surface.py`
- `tests/test_validate_parser_element_micro_eval_surface.py`

Gate checks:

- Fixed query-set hash:
  `72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5`.
- Aggregate mode/schema, hashing backend, section chunking, `top_k=6`, and the
  routing-v2 12-doc element stream marker.
- `12` documents, `6` queries, `6/6` same-hit passed, `6/6` top-1 row hits,
  `5/6` top-1 same-hit matches, same-hit MRR `0.875`; the sole allowed
  top-1 same-hit miss is `text_row48_compliance_table`.
- Required source coverage: `metadata_fact`, `ocr_text`, `table`, `text_layer`.
- Required expected element type coverage: `metadata_fact`, `ocr_text`, `table`,
  `text_layer`.
- Textless aggregate: rejects raw/text-like keys such as `query`, `text`,
  `chunk_text`, `raw_text`, and `content`.

Validation:

```bash
python3 scripts/validate_parser_element_micro_eval_surface.py
```

Result:

```json
{"surface": "parser_element_micro_eval_v0", "status": "valid", "queries": 6, "passed": 6, "top1_hits": 5, "top1_row_hits": 6, "mrr": 0.875}
```

Decision:

- The candidate surface now has a reproducible validation gate.
- It still remains candidate-only until ADR/evaluation-surface registration
  explicitly promotes it.

## Progress — 2026-06-05 Phase 26 ADR 0102 promotion

Goal: promote the validated candidate gate to an official reviewer-facing
measurement surface without turning it into a parser-quality benchmark.

Added/updated:

- `docs/adr/0102-parser-element-micro-eval-wiring-surface.md`
- `docs/adr/README.md`
- `docs/evaluation/surface-map.md`

Decision:

- `parser_element_micro_eval_v0` is now the official surface name.
- Allowed claim: parser element stream wiring/searchability did or did not
  regress for metadata, routed OCR, table sidecars, text-layer control, and
  path-alias scoring.
- Disallowed claims: PDF parser quality, OCR accuracy, table structure quality,
  chart/diagram/VLM semantic extraction quality, real100_v2 retrieval/answer
  quality, or canonical ingestion replacement.
- This surface is reviewer evidence only; it is not a CI-required gate and does
  not change canonical ingestion defaults.

## Progress — 2026-06-05 Phase 27 self-describing aggregate hash

Goal: make the official ADR 0102 aggregate self-describing without exposing raw
query text.

Updated:

- `scripts/run_parser_element_stream_retrieval_smoke.py`
- `scripts/validate_parser_element_micro_eval_surface.py`
- `tests/test_parser_element_stream_retrieval_smoke.py`
- `tests/test_validate_parser_element_micro_eval_surface.py`

Decision:

- `retrieval_smoke.aggregate.json` now records `run.query_set_hash`.
- The markdown report prints the query-set hash.
- The validator requires the aggregate `run.query_set_hash` to match ADR 0102's
  fixed hash:
  `72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5`.
- Raw query text still stays out of the aggregate.
