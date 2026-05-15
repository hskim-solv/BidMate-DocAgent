# 0036: HwpNativeLoader promoted to pyhwp-gated default

- **Status**: superseded by [0049](./0049-kordoc-replaces-pyhwp-backend.md)
- **Date**: 2026-05-13
- **Superseded**: 2026-05-15 — pyhwp 0.1b15 API drift recorded `hwp_native_rate = 0.0` on the private 100-doc real-eval (paragraph-only extraction lost table/heading structure RFPs rely on). [ADR 0049](./0049-kordoc-replaces-pyhwp-backend.md) replaces the pyhwp backend with kordoc (npm subprocess) and keeps `csv_text` as the unconditional fallback.
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md) (baseline invariant), [`ingestion.py:_resolve_loader`](../../ingestion.py) (loader routing), [issue #167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167) (original spike), [issue #363](https://github.com/hskim-solv/BidMate-DocAgent/issues/363) (observability), [issue #365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) (this decision), [issue #426](https://github.com/hskim-solv/BidMate-DocAgent/issues/426) (implementation)

## Context

`HwpNativeLoader` (`ingestion.py:L131`) was added in issue #167 as an opt-in spike
behind `BIDMATE_HWP_LOADER=native`. After issue #363 added `RuntimeWarning` +
`last_fallback_reason` observability, the fallback path is measurable.

The Pre-Phase-3 audit flagged the env-var gate as a "scaffold that became
load-bearing" — Korean RFP users who actually need table-structure extraction must
explicitly set the env var, meaning the better parser is invisible by default. The
`with_tables=True` variant (`BIDMATE_HWP_LOADER=native_tables`, issue #506) compounds
this: two undiscoverable knobs control a critical path for the target corpus.

## Decision

`_resolve_loader` (implementation tracked in issue #426) will detect pyhwp availability
via `importlib.util.find_spec("hwp5")` and default to `HwpNativeLoader(with_tables=True)`
when the package is present. `BIDMATE_HWP_LOADER=csv` becomes the explicit opt-out for
environments that need the CSV-only path.

Env-var precedence (highest to lowest):
1. `BIDMATE_HWP_LOADER=csv` → `LOADERS["hwp"]` (CSV fallback, explicit opt-out)
2. `BIDMATE_HWP_LOADER=native` → `HwpNativeLoader(with_tables=False)` (text-only native)
3. `BIDMATE_HWP_LOADER=native_tables` → `HwpNativeLoader(with_tables=True)` (text + tables)
4. *(unset or empty)* + pyhwp importable → `HwpNativeLoader(with_tables=True)` **← new default**
5. *(unset or empty)* + pyhwp absent → `LOADERS["hwp"]` (unchanged; CI minimal install safe)

`HwpNativeLoader.load()` already catches `ImportError` and falls back to CSV text with a
`RuntimeWarning`, so case 5 is a safety net, not a new code path.

## Consequences

**Easier:**
- Korean RFP users with pyhwp installed get table structure by default — no env-var
  documentation lookup required.
- The observable `last_fallback_reason` field (issue #363) now surfaces real-world
  pyhwp failures rather than the env-var-never-set case, making it a useful signal.
- `BIDMATE_HWP_LOADER=csv` is a discoverable, documented opt-out rather than the
  invisible default.

**Harder / constrained:**
- pyhwp becomes a documented optional dependency; `requirements-dev.txt` or a separate
  `requirements-hwp.txt` must declare it so contributors can opt in.
- CI smoke/test runs without pyhwp must cover case 5 (CSV fallback) to catch any
  import-detection regression. The existing `EMBEDDING_BACKEND=hashing` minimal install
  already satisfies this.
- ADR 0001 naive-baseline invariant is preserved: the `naive_baseline` eval preset does
  not load HWP files; the loader default change has no effect on eval bit-stability.

**Re-open condition:**
If native-loader fallback rate on the private 100-doc corpus exceeds 20% after one
`make real-eval` cycle with `BIDMATE_HWP_LOADER` unset, revisit the default or the
pyhwp detection logic.

## Alternatives considered

- **Option 1 — Deprecate**: removes table-extraction capability for Korean RFP users
  without measuring whether it was ever used. Premature given pyhwp already works.
- **Option 3 — Integrate into visual_ingestion v2**: the right long-term seam, but
  `visual_ingestion.py` v2 is not yet scoped. Blocking this decision on a phase-3 refactor
  delays the discoverability fix indefinitely.
- **Option 4 — Keep + Observe**: status quo env-var gate. After issue #363 landed,
  the observability is in place to measure. Deferring further accumulates evidence but
  leaves a better parser invisible to most users for another eval cycle.
