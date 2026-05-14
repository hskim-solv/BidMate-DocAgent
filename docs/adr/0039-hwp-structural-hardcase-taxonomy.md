# 0039: HWP structural hardcase taxonomy for public synthetic surface

- **Status**: proposed
- **Date**: 2026-05-14
- **Deciders**: hskim-solv
- **Related**: issue #646, ADR 0001, ADR 0005, ADR 0030, ADR 0036, [docs/private-hardcase-benchmark.md](../private-hardcase-benchmark.md)

## Context

ADR 0036 (#641) introduced HwpNativeLoader as the pyhwp-gated default, making the private 100-doc eval corpus 96% HWP. The public synthetic surface, however, has no HWP fixtures and its 22 hardcase entries (14 `hardcase_categories` + 8 abstention, [`eval/config.yaml:880-996`](../../eval/config.yaml)) cover only logical and retrieval discrimination — not document-structure failures.

[`docs/private-hardcase-benchmark.md:24-31`](../private-hardcase-benchmark.md) defines five document-structure slices (`scanned_pdf`, `rotated_or_skewed`, `table_heavy`, `mixed_layout`, `noisy_ocr`) for the private surface only. The public `by_hardcase_category` aggregate ([`eval/run_eval.py:618`](../../eval/run_eval.py)) automatically buckets any category tag found in case config, so adding tags requires no code change — only a policy decision on which slices are safe to introduce publicly.

Without this taxonomy, the effect of HWP loader selection (csv-text vs native vs native_tables, ADR 0036) on citation precision or table-cell recall cannot be measured on the public surface, and ADR 0030 leaderboard cannot expose an HWP-specific accuracy time series.

## Decision

Admit four HWP structural hardcase categories to the public synthetic surface — `table_heavy`, `ocr_noisy`, `rotated_or_skewed`, and `layout_broken` — using only synthetic fixtures that contain no private document content. Cases tagged with these categories must satisfy all three constraints:

1. **ADR 0001 baseline invariant**: tagging is additive; it must not alter the retrieval, verifier, or answer path for any existing case.
2. **ADR 0005 public boundary**: fixtures must be redistributable synthetic JSON (matching the existing `data/raw/rfp_agency_*.json` schema); no scanned or OCR-extracted private snippets.
3. **ADR 0030 forward-only**: introducing new `by_hardcase_category` keys creates a series break; past snapshots render as `—` and no backfill is required.

Subsequent PRs activate this taxonomy: PR-A adds synthetic HWP fixtures and initial tagged cases; PR-D tags additional cases once the loader ablation data (PR-C) confirms which query types are most discriminated by table vs. layout failures.

## Consequences

- `by_hardcase_category` in `eval_summary.json` gains four new keys; the existing 22 slices are unaffected.
- Leaderboard (ADR 0030) can render `table_heavy` citation-precision and `layout_broken` groundedness series alongside `naive_baseline` / `agentic_full`.
- HWP loader ablation (PR-C: `hwp_csv_text` / `hwp_native` / `hwp_native_tables`) becomes measurable against these structural slices.
- CI runs with no pyhwp installed remain green: fixtures are JSON, so `_resolve_loader` ([`ingestion.py:377`](../../ingestion.py)) is not invoked.
- Teams adding new private hardcase slices must check against this list to avoid naming collisions in the shared `by_hardcase_category` namespace.

## Alternatives considered

- **Admit `scanned_pdf` and `mixed_layout` as well**: deferred. Scanned-PDF fixtures require image data or OCR-corpus segments that risk private content leakage; `mixed_layout` overlaps semantically with `layout_broken` and would need disambiguation guidance before public use.
- **Keep all structural slices private-only**: rejected. Keeps ADR 0036 loader impact invisible to the public leaderboard, making the capability argument non-verifiable externally — directly countering the portfolio-visibility goal that motivated ADR 0036.
