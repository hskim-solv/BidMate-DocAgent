# Plan: T-2026-0004 PDF/HWP PyMuPDF4LLM canonical citation loader

- Status: done
- Owner role: Implementer -> Reviewer
- Related task: `tasks/queue.md::T-2026-0004`
- Related issue / PR: implementation PR [#1494](https://github.com/hskim-solv/BidMate-DocAgent/pull/1494); refresh issue [#2118](https://github.com/hskim-solv/BidMate-DocAgent/issues/2118)
- Related ADR: ADR 0078, ADR 0049, ADR 0001
- Created: 2026-05-26
- Last updated: 2026-06-04

## Problem Statement

HWP/PDF evidence now needs reproducible page citations. `kordoc` preserves useful structure
but is page-blind for citation-bearing answers. Local HWP comparison also showed that Hancom
and LibreOffice can produce different page counts for the same HWP, so citations must point
to a named PDF artifact, not to an abstract "HWP page".

## Desired Behavior

Use `pdf_pymupdf4llm` as the default loader for both HWP and PDF. PDF files are parsed
directly with `pymupdf4llm.to_markdown(..., page_chunks=True)`. HWP files are converted
to a preserved LibreOffice PDF artifact first, then parsed with the same page-chunk path.
Parser failures fail closed; CSV fallback is only available through explicit
`BIDMATE_{HWP,PDF}_LOADER=csv_text`.

## Constraints

- Preserve ADR 0001 by keeping explicit `csv_text` behavior available.
- Do not auto-install LibreOffice extensions such as H2Orestart.
- Do not treat LibreOffice exit status alone as success; validate a non-empty, openable PDF.
- Keep private source paths and filenames out of stored fallback diagnostics.
- Do not call HWP citations "original HWP pages"; label them as LibreOffice converted PDF pages.

## Affected Interfaces

- CLI/config: `scripts/build_index.py --hwp_loader pdf_pymupdf4llm --pdf_loader pdf_pymupdf4llm`.
- CLI/config: `scripts/build_index.py --hwp_pdf_artifact_dir <dir>` defaults to
  `<output_dir>/hwp_pdf_artifacts`.
- Env: `BIDMATE_HWP_TO_PDF_CMD`, `BIDMATE_HWP_TO_PDF_INFILTER`,
  `BIDMATE_HWP_TO_PDF_TIMEOUT`, `BIDMATE_HWP_PDF_ARTIFACT_DIR`.
- Output artifacts: `ingestion_report.json::summary.text_source_counts` can include
  `{hwp,pdf}.pdf_pymupdf4llm`; `summary.parser_health` records skipped numeric-only chunks.
- Answer citations: additive `citation_label`, `citation_basis`, PDF hashes, and `text_span_hash`.

## Acceptance Criteria

- [x] `_resolve_loader("hwp")` defaults to `HwpPdfPyMuPdf4LlmLoader`.
- [x] `_resolve_loader("pdf")` defaults to `PdfPyMuPdf4LlmLoader`.
- [x] Explicit `kordoc` remains available but is provenance-WARNed as legacy/non-canonical.
- [x] Loaders preserve page sections and `page_span` on success.
- [x] Converter unavailable, nonzero exit, missing PDF, invalid PDF, unavailable parser,
  empty parser output, and parser exceptions fail closed with stable reason keys.
- [x] HWP converted PDF artifact metadata is preserved.
- [x] Answer citations include canonical citation labels and no private artifact path.
- [x] Comparison script records `libreoffice_pymupdf4llm` separately from visual-v2.

## Validation Strategy

```bash
python3 -m unittest tests.test_hwp_pdf_pymupdf4llm_loader -v
python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py -q
python3 -m py_compile ingestion.py scripts/build_index.py scripts/compare_hwp_extraction.py tests/test_hwp_pdf_pymupdf4llm_loader.py
```

## Rollback Strategy

Remove the opt-in loader, CLI choice, comparison-script path, optional requirements file,
and regression tests. Do not change `kordoc`, `csv_text`, or existing cached extraction
artifacts during rollback.

## Reviewer Notes

Attack fallback correctness first: the historical LibreOffice failure must not be reported
as parser success, and private path/filename details must not leak through fallback reasons.
