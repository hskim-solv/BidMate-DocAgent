# Plan: T-2026-0024 Page Metadata Reindex

- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0024`
- Related issue / PR: [#1573](https://github.com/hskim-solv/BidMate-DocAgent/issues/1573) / PR TBD

## Problem

The page metadata blocker was misdiagnosed as missing conversion output. The
local `real100_v2` private artifacts include 100 parsed Markdown exports, 94
converted PDFs, and 100 parse checkpoints. The useful recovery source is the
checkpointed parser document shape: sections already carry explicit
`page_span`. The stale index lost that metadata because fixed chunking built a
document-wide parent section from section text while only aggregating
`regions`, not `page_span`.

## Desired Outcome

Rebuild private indexes with page metadata available on chunks before choosing
multi-chunk retrieval changes, without changing retrieval ranking, verifier,
prompt, answer, or eval scoring behavior.

## Scope

- Preserve explicit section-level `page_span` through `fixed_parent_section`.
- Keep the existing `make real-eval` defaults unchanged.
- Add an isolated `real-eval-page-aware` target for local page-aware rebuilds
  that reuse private converted PDFs and write to separate output paths.
- Record only aggregate validation evidence.

## Out Of Scope

- No MiniLM/BGE-M3 baseline decision; issue #1575 covers embedding baseline
  separation.
- No retrieval, reranking, query decomposition, section expansion, verifier, or
  answer runtime change.
- No raw private text, filenames, doc IDs, chunk IDs, checkpoint payloads, or
  local paths in committed artifacts.

## Implementation Notes

- `ingestion._sections_from_pymupdf4llm_output()` already creates page sections
  with `page_span`.
- `ingestion._sections_from_loader()` and `normalize_ingestion_row()` already
  preserve loader sections into document payloads.
- `rag_indexing.make_chunk()` already copies parent `page_span` into chunks.
- The smallest lossy boundary is `rag_metadata_processing.fixed_parent_section`;
  it now aggregates explicit section page spans when fixed chunking builds a
  document parent section.

## Validation

```bash
bash -n scripts/smoke_real.sh
python3 -m pytest -q tests/test_smoke_real_script.py tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_build_private_real100_v2_parallel.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_export_private_index_markdown.py
python3 -m py_compile ingestion.py rag_metadata_processing.py rag_indexing.py scripts/build_private_real100_v2_parallel.py scripts/build_index.py
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_pageaware" --format markdown
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_fixed_pageaware" --format markdown
git diff --check
make check-branch
```

## Evidence

- Local section page-aware rebuild from cached checkpoints completed with 100
  documents and 24,613 chunks.
- Local fixed rebuild from the same cached checkpoints completed with 100
  documents and 21,800 chunks.
- Aggregate-only page metadata audit for both isolated rebuilds reported
  citation page claim `GO`, chunk page metadata coverage 1.0, and chunk
  `page_span` coverage 1.0.

## Reviewer Focus

- Confirm the change is metadata propagation only; retrieval ranking inputs and
  answer generation are unchanged.
- Confirm aggregate-only reporting and no private path/raw text leakage.
- Confirm the PR does not claim performance improvement.
- Confirm the documentation distinguishes coarse fixed chunk page ranges from
  section/page-aware citation precision.

## Session Handoff

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: `fix/issue-1573-page-metadata-reindex` / Codex worktree
- Current status: implementation done; final validation and PR still needed.
- Files touched: `Makefile`, `scripts/smoke_real.sh`,
  `rag_metadata_processing.py`, `tests/test_page_aware_parser_contract.py`,
  `tests/test_smoke_real_script.py`, `docs/plans/T-2026-0024-page-metadata-reindex.md`,
  `tasks/queue.md`.
- Commands run: `bash -n scripts/smoke_real.sh`; `python3 -m pytest -q tests/test_smoke_real_script.py tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_build_private_real100_v2_parallel.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_export_private_index_markdown.py`; `python3 -m py_compile ingestion.py rag_metadata_processing.py rag_indexing.py scripts/build_private_real100_v2_parallel.py scripts/build_index.py`; `python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_pageaware" --format markdown`; `python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_fixed_pageaware" --format markdown`.
- Results: section page-aware local rebuild from checkpoints reports 100
  documents / 24,613 chunks / 1.0 chunk page-span coverage. Fixed rebuild
  reports 100 documents / 21,800 chunks / 1.0 chunk page-span coverage.
- Blockers: none known.
- Open risks: fixed chunking produces coarse document-range page spans; precise
  page citation quality still needs separate evaluation before claims.
- Next action: run final validation and open PR.
- Next safe command: `python3 -m pytest -q tests/test_smoke_real_script.py tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_build_private_real100_v2_parallel.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_export_private_index_markdown.py`
- Reviewer focus: page metadata propagation, privacy-safe evidence, no
  performance claim.
- Eval surface: ingestion/index metadata propagation; no retrieval ranking or
  answer behavior change intended.
