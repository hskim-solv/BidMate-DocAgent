---
title: HWP Eval Gap Closure
layout: page
permalink: /hwp-eval-closure/
---

# HWP Eval Gap Closure (ADR 0039)

This document records the four gaps identified in May 2026 between the
public synthetic eval surface and the private 100-doc corpus (96% HWP),
and the PR stack that closed them.

## Background

After ADR 0036 (#641) shipped `HwpNativeLoader` as the pyhwp-gated default,
the private corpus was 96 HWP + 4 PDF
([`data/index/real100/ingestion_report.json`](../../data/index/real100/ingestion_report.json)).
Three questions surfaced:

1. Is HWP data actually exercised in the public eval?
2. Do the public eval questions discriminate real-data quality?
3. Is hard-case evaluation (structural defects) possible?

Code-level inspection found four gaps:

| # | Gap | Before | After |
|---|-----|--------|-------|
| 1 | Public synthetic eval에 HWP fixture 없음 | 100 cases, JSON corpus only | 105 cases (+5 HWP hardcase) |
| 2 | `eval_summary.json`에 `by_format` 없음 | HWP vs PDF 분리 불가 | `by_format.hwp` aggregate 추가 |
| 3 | HWP loader ablation preset 없음 | `naive_baseline` / `agentic_full`만 | `hwp_csv_text` / `hwp_native` / `hwp_native_tables` 3-way |
| 4 | 공개 hardcase에 구조 카테고리 없음 | retrieval/abstention 변별만 (22 cases) | +4 구조 카테고리 활성 (ADR 0039) |

## PR Stack (ADR 0039 Kahn-ordered)

```
main
 └─ PR-0  ADR 0039 — HWP structural hardcase taxonomy (docs only)
     └─ PR-A  공개 synthetic HWP fixture 2개 + 5 eval cases
         └─ PR-B  eval_summary by_format aggregate + SAFE_FORMAT_BUCKET_KEYS
             └─ PR-C  hwp_csv_text / hwp_native / hwp_native_tables ablation preset
                 └─ PR-D  ADR 0039 rotated_or_skewed + ocr_noisy 카테고리 활성
                     └─ PR-E  leaderboard HWP slice (this PR)
```

| PR | Issue | Branch | Key files |
|----|-------|--------|-----------|
| PR-0 | #646 | `docs/issue-646-adr-0039-hwp-hardcase` | `docs/adr/0039-hwp-structural-hardcase-taxonomy.md` |
| PR-A | #648 | `feat/issue-648-hwp-synthetic-fixture` | `data/raw/rfp_agency_f/g_hwp.json`, `eval/config.yaml` (+5 cases) |
| PR-B | #650 | `feat/issue-650-eval-by-format-breakdown` | `eval/run_eval.py`, `scripts/run_real_eval_delta.py`, `tests/test_eval_by_format_aggregate_regression.py` |
| PR-C | #652 | `feat/issue-652-hwp-loader-ablation` | `eval/config.yaml` (+3 ablation rows), `scripts/build_index.py` (`--hwp_loader`) |
| PR-D | #654 | `feat/issue-654-hwp-hardcase-tagging` | `eval/config.yaml` (tagging only) |
| PR-E | #657 | `feat/issue-657-leaderboard-hwp-surface` | `scripts/leaderboard.py`, `docs/hwp/hwp-eval-closure.md` (this file) |

## What each gap closure delivers

### Gap 1: HWP fixture (PR-A)

Two synthetic JSON fixtures with `metadata.source_format: "hwp"`:
- `rfp-agency-f-smart-factory-hwp` — table-heavy budget spec (4억 3,500만원)
- `rfp-agency-g-traffic-hwp` — layout-broken traffic management RFP (2억 8,000만원)

Five new eval cases cover `single_doc`, `comparison`, `follow_up`, and
`abstention` query types. No `.hwp` binary committed (copyright; ADR 0005
public/private boundary).

### Gap 2: by_format aggregate (PR-B)

`eval/run_eval.py:summarize_run` now groups results by `metadata.source_format`.
`eval_summary.json` gains a top-level `by_format` key:

```json
{
  "by_format": {
    "hwp": { "num_predictions": 2, "accuracy": 0.85, ... },
    "synthetic_public_sample": { "num_predictions": 103, ... }
  }
}
```

`SAFE_FORMAT_BUCKET_KEYS = frozenset({"hwp", "pdf", "synthetic_public_sample"})`
is the fail-closed whitelist in `run_real_eval_delta.py` (ADR 0005 guard).

### Gap 3: Loader ablation preset (PR-C)

`eval/config.yaml:ablation_runs` gains three rows (`hwp_csv_text`,
`hwp_native`, `hwp_native_tables`), all built on `pipeline: agentic_full`
(ADR 0001 baseline invariant preserved). `scripts/build_index.py` gains
`--hwp_loader {csv,native,native_tables}` which sets `BIDMATE_HWP_LOADER`
before `_resolve_loader` in `ingestion.py` runs.

### Gap 4: Structural hardcase categories (PR-D)

Four ADR 0039 categories activated in `eval/config.yaml`:

| Category | Fixture cases tagged |
|----------|---------------------|
| `table_heavy` | hwp_f_table_budget |
| `layout_broken` | hwp_g_layout_contract_amount |
| `rotated_or_skewed` | hwp_g_layout_contract_amount, hwp_compare_fg_scale |
| `ocr_noisy` | hwp_g_layout_contract_amount, hwp_compare_fg_scale |

`by_hardcase_category` in `eval/run_eval.py` absorbs any category key
automatically — no code change required.

## Leaderboard visibility (PR-E)

`scripts/leaderboard.py` now renders:
- A third **HWP Slice** table (`## HWP Slice: by_format[hwp]`) in
  `reports/leaderboard.md`
- A `hwp_format` Chart.js series (teal line) in each headline metric chart
  on the GitHub Pages leaderboard

Past snapshots show `—` per ADR 0030 forward-only policy. New CI runs on
`main` populate the series going forward.

## Invariant checklist

- [x] ADR 0001: `naive_baseline` preset unchanged; new ablation rows are additive
- [x] ADR 0005: No per-case payload in committed aggregates; `SAFE_FORMAT_BUCKET_KEYS` is fail-closed
- [x] ADR 0007: All branches are `<type>/issue-<N>[-<slug>]`; all PRs have `Closes #N`
- [x] ADR 0030: Leaderboard is forward-only; pre-PR-B snapshots show `—` in HWP slice
- [x] ADR 0036: pyhwp-absent CI safe — fixtures are JSON, `.hwp` binary not committed
- [x] ADR 0039: Status promoted from proposed → accepted with PR-D merge
