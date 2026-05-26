# 0078: PyMuPDF4LLM Canonical Page Citation

- **Status**: accepted
- **Date**: 2026-05-26
- **Deciders**: project maintainer, Codex
- **Related**: supersedes ADR 0049 defaults for HWP/PDF citation-bearing ingestion

## Context

RFP answers need page-cited evidence. The previous `kordoc` default preserves HTML table structure, but it is page-blind for HWP/PDF citation and cannot safely support page-based evidence. Local comparison also showed that HWP pages are renderer-dependent: Hancom and LibreOffice produced different page counts for the same HWP, so citations must name the exact PDF artifact they refer to.

LibreOffice/H2Orestart can convert HWP to PDF in the local environment, but the path has known hard failures (`pdf_not_produced`, `source file could not be loaded`, Java extension loader issues). Silent CSV fallback would create citation-free chunks and contaminate evaluation, so citation builds must fail closed.

## Decision

Use PyMuPDF4LLM page chunks as the canonical citation parser for both PDF and HWP.

- PDF files are parsed directly with `pymupdf4llm.to_markdown(..., page_chunks=True)` and cite the source PDF pages.
- HWP files are first converted by LibreOffice/soffice to a preserved citation PDF, then parsed by PyMuPDF4LLM.
- HWP default loader becomes `pdf_pymupdf4llm`; PDF default loader also becomes `pdf_pymupdf4llm`.
- `kordoc` remains an explicit legacy opt-in for non-canonical extraction, but it is not page-citation-ready.
- CSV fallback is available only by explicit `BIDMATE_{HWP,PDF}_LOADER=csv_text`; canonical parser failures fail the build.

## Consequences

- Answer citations can include `page_span`, `citation_label`, `citation_basis`, PDF hash metadata, and `text_span_hash`.
- HWP citation labels mean `LibreOffice 변환 PDF p.N`, not original-HWP p.N.
- HWP converted PDFs must be preserved with stable hashes so page citations are reproducible.
- Table fidelity may be worse than `kordoc` HTML output, but citation correctness is prioritized for RFP evidence.
- Eval health should track `pdf_pymupdf4llm_rate` and `page_citation_ready_rate` rather than `kordoc_rate`.

## Alternatives considered

- Keep `kordoc` as default and add page citation only where available: rejected because HWP evidence would silently mix page-aware and page-blind chunks.
- Use Hancom-generated PDFs as canonical artifacts: rejected for the default path because Hancom is paid/proprietary.
- Permit CSV fallback with no-citation flags: rejected for citation builds because answer generation and eval could still consume citation-free chunks.

## Verification

<!-- verifies-key: ingestion.py:PdfPyMuPdf4LlmLoader -->
<!-- verifies-key: ingestion.py:LIBREOFFICE_CONVERTED_PDF_CITATION_BASIS -->
<!-- verifies-key: rag_answer.py:citation_label -->
<!-- verifies-key: eval/run_eval.py:page_citation_ready_rate -->
