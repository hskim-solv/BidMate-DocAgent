# 0049: kordoc replaces pyhwp/hwp5 as HWP/PDF parser backend

- **Status**: proposed
- **Date**: 2026-05-15
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (csv_text baseline preserved), [ADR 0036](./0036-hwp-native-loader-pyhwp-gated-default.md) (superseded by this), issue [#890](https://github.com/hskim-solv/BidMate-DocAgent/issues/890) (this ADR), issue [#801](https://github.com/hskim-solv/BidMate-DocAgent/issues/801) (`hwp_native_rate > 0.0` goal — superseded surface), PR [#856](https://github.com/hskim-solv/BidMate-DocAgent/pull/856) (closed: pyhwp 0.1b15 sections API adapt — superseded by this), PR [#895](https://github.com/hskim-solv/BidMate-DocAgent/pull/895) (this PR — extended to PDF mid-review after the kordoc-vs-csv_text PDF measurement showed 22×–757× content-size gap)

## Context

By 2026-05-15 the private 100-doc real-eval recorded `hwp_native_rate = 0.0` — all 96 HWP files fell back to `data_list_csv_text` (single-column CSV text). Root cause was a pyhwp 0.1b15 API drift (`BodyText.section_list()` removed in favor of `sections` attribute, paragraph traversal replaced with event streams). PR #787 added the resulting `AttributeError` to the fallback tuple so builds no longer aborted, but the silent degradation hid the regression — ADR 0036's "pyhwp-gated native default" decision became effectively dead code on the private corpus.

PR #856 adapted both pyhwp API generations in `ingestion._extract_hwp_native`. The adaptation passes 41 unit tests but (1) its real-eval delta cannot be measured on the dev host (pyhwp is an opt-in dependency the dev host lacks) and (2) even when pyhwp works, the paragraph-only extraction discards table structure, headings, and form-document layout that public RFP documents rely on.

A 2026-05-15 Phase 1 dump experiment ran [chrisryugj/kordoc](https://github.com/chrisryugj/kordoc) (npm, MIT) against `data/files/`: HWP 96 + PDF 4 = **100/100 converted**, 13.5s + 19.5s = 33s total, 19MB Markdown output. Output preserves HTML `<table>` with `colspan`/`rowspan`, Korean headings (`### □`, `### ⚬`), footnotes, and nested-table markers — the exact structure paragraph-only pyhwp extraction loses.

## Decision

Replace `ingestion.HwpNativeLoader`'s pyhwp/hwp5 backend with `HwpKordocLoader`, and replace `PdfCsvTextLoader`'s default path with `PdfKordocLoader`. Both shell out to a *single* `npx -y -p kordoc -p pdfjs-dist kordoc <files…> -d <out>/` invocation per ingestion run (orchestrated by `_prime_kordoc_batches`), then route the resulting Markdown into per-format loader caches by file extension. Keep `csv_text` as the unconditional fallback for both formats to preserve ADR 0001 naive baseline.

PDF was originally scoped out of the first iteration of this ADR but pulled back in after a mid-review measurement: csv_text PDF extraction held only 220–2,716 chars per document (cover + TOC only), while kordoc held 60,572–268,877 chars with 24–198 `<table>` blocks each — a 22×–757× content-size gap on the 4-PDF private slice, larger than the HWP `hwp_native_rate=0.0` silent-failure gap that originally motivated this ADR.

- **env switches**: `BIDMATE_HWP_LOADER=kordoc` (default) | `csv_text`; `BIDMATE_PDF_LOADER=kordoc` (default) | `csv_text`. Each format flips independently. Both auto-degrade to `csv_text` on `node --version` failure or `npx` exit-code error, mirroring ADR 0036's fallback discipline.
- **Telemetry surface**: `{Hwp,Pdf}KordocLoader.last_text_source ∈ {"kordoc", "data_list_csv_text"}` and `last_fallback_reason` keep the shape ADR 0036's loader established, so `reports/eval_summary.json::text_source_counts` reads `{"hwp": {"kordoc": N}, "pdf": {"kordoc": M}}` after this PR. The eval `kordoc_rate` aggregation that originally targeted HWP applies to both formats now.
- **Single-subprocess batching**: `_prime_kordoc_batches` pools HWP + PDF paths into one `npx kordoc` call so the npm fetch + Node spin-up cost is paid once per ingestion, not twice. Per-format cache routing happens after the subprocess returns.
- **pyhwp/hwp5 removal**: pyhwp is *not* pinned in any `requirements*.txt` — `ingestion.py` only imports it lazily under a `find_spec("hwp5")` gate. This PR removes the lazy imports and gate; no requirements diff is needed. If pyhwp lives in a dev shell elsewhere it is now dead weight, removable in a future cleanup at zero risk.

## Consequences

- **Information gain on the private corpus**. Table structure, headings, and form-document layout survive — the surface most retrieval-failure-mode analyses on RFP documents pin as missing. Real-eval delta is the measurement contract (issue #890 acceptance criterion 7).
- **Host-dependency simplification**. The "pyhwp not installed in this worktree" caveat that blocked PR #856's §5b real-data delta disappears — `node --version` is the single check, and the fallback path (`csv_text`) is identical to today's behavior.
- **New runtime dependency: Node.js 18+**. CI runners and the `make install` flow gain a Node setup step (`pr-eval.yml` change scoped to issue #890). First-run `npx kordoc` fetches ~tens of MB; cached on the runner. Air-gapped environments are forced to `csv_text` (graceful, telemetry-visible).
- **kordoc OSS stability risk**. kordoc shipped 2026-04 and is one-author. The same drift mode that broke pyhwp can break kordoc — but the telemetry surface (`last_text_source` / `last_fallback_reason` / `text_source_counts`) is identical, so the next drift produces the same loud signal (`kordoc_rate → 0`) that pyhwp's drift produced silently because no one was watching ADR 0036's metric.
- **Locks csv_text invariant**. The naive-baseline `csv_text` extraction path is now *load-bearing for offline correctness*, not just for ADR 0001 comparison — removing it would break the kordoc-missing-host case. Any future ADR that proposes removing csv_text must replace this fallback surface explicitly.
- **Supersedes ADR 0036**. ADR 0036's "pyhwp-gated native default" is no longer a live design; same PR updates ADR 0036's Status block to `superseded by 0049` with a one-line resolution note.

## Alternatives considered

- **pyhwp 0.1b15 sections-API adapt (PR #856)**. 41 unit tests pass, but real-eval delta blocked by dev-host pyhwp absence (PR #856 §5b admitted this) and paragraph-only extraction loses table structure RFPs rely on. Rejected: the §5b admission alone fails CLAUDE.md's load-bearing real-data-delta requirement, and the structural loss is not recoverable inside the pyhwp surface.
- **LibreOffice `--headless --convert-to`**. JVM/Java runtime, slower per-file, and table-to-markdown still needs a separate post-process step. Rejected: heavier than the Node 18 dependency we're adding, with worse structure preservation.
- **pdfminer/PyMuPDF + alternative HWP parser combo**. PDF and HWP paths fork into two unrelated code surfaces; kordoc collapses them under one CLI invocation. Rejected: integration surface bloat.
- **kordoc MCP server (`kordoc mcp`)** rather than CLI subprocess. ingestion pipeline runs as a deterministic batch — MCP's message-passing model adds asynchrony overhead with no upside for the batch case. Rejected: wrong tool for the indexing path; the MCP server is the right tool for interactive AI-client usage, which is out of scope for this ADR.

## Verification

The Decision binds four measurement surfaces. The pre-commit lint resolves the keys below to existing files once the kordoc PR lands (the new files are created by the kordoc PR itself):

<!-- verifies-key: ingestion.py:HwpKordocLoader -->
<!-- verifies-key: ingestion.py:PdfKordocLoader -->
<!-- verifies-key: tests/test_ingestion_kordoc_regression.py:test_ -->
<!-- verifies-key: reports/eval_summary.json:text_source_counts -->
<!-- verifies-key: docs/adr/0036-hwp-native-loader-pyhwp-gated-default.md:superseded -->

Reading guide:

- `ingestion.py:HwpKordocLoader` — the loader class that replaces `HwpNativeLoader`; its `last_text_source` enum and fallback semantics are the runtime evidence that this ADR's Decision shipped.
- `tests/test_ingestion_kordoc_regression.py:test_` — regression tests that pin (a) kordoc CLI invocation shape, (b) Node-missing → `csv_text` fallback, (c) telemetry-key stability. Skip-guarded so CI without Node still runs the fallback case.
- `reports/eval_summary.json:text_source_counts` — eval surface that emits `{"kordoc": N, "data_list_csv_text": M}`. The kordoc PR's real-eval delta (issue #890 §7) is the first read of this; future drift detection (analogous to ADR 0036's silent failure mode) re-reads it.
- `docs/adr/0036-hwp-native-loader-pyhwp-gated-default.md:superseded` — ADR 0036's Status block updated to `superseded by 0049` in the same PR. Lints catch the lockstep — if this ADR ships without ADR 0036's update, the marker resolves but `superseded` substring is absent.

Running `python3 scripts/_governance.py --lint-adr-consequences docs/adr/0049-kordoc-replaces-pyhwp-backend.md` from repo root must exit 0 once the kordoc PR's files are committed.
