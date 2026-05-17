# Real-100 Corpus EDA

Aggregate-only profile of the private 100-document RFP dataset. ADR 0005 boundary: 사업명 / 사업 요약 / 텍스트 / 파일명 are read for length statistics only; never rendered. Agency names beyond rank 10 are anonymized to `agency_NN` labels.

Sources: `data/data_list.csv`, `data/index/real100/index.json`, `reports/real100/baseline.aggregate.json`

## Axis 1 — Metadata domain

- Total docs: **100**
- Unique agencies: **87** (top 10 below, 78 docs in long tail)
- File formats: `hwp`=96, `pdf`=4

### Agency distribution (top)

| rank | agency | doc count |
|---|---|---|
| 1 | 한국수자원공사 | 3 |
| 2 | 한국철도공사 (용역) | 3 |
| 3 | 한국연구재단 | 2 |
| 4 | 한국생산기술연구원 | 2 |
| 5 | 인천광역시 | 2 |
| 6 | 국방과학연구소 | 2 |
| 7 | 수협중앙회 | 2 |
| 8 | 한국농어촌공사 | 2 |
| 9 | 축산물품질평가원 | 2 |
| 10 | 광주과학기술원 | 2 |
| … | _(rank 11+, anonymized)_ | 78 |

### Budget (KRW) — available rows only

- available: 93 / missing: 7
- p10 / p50 / p90: **5.00천만 / 19.60천만 / 10.77억**
- min / max: 1 / 141.07억

### Text-length distribution (chars; raw text never rendered)

| field | p50 | p95 | max | mean |
|---|---|---|---|---|
| 사업명 | 29 | 48 | 65 | 30 |
| 사업 요약 | 249 | 395 | 524 | 269 |
| CSV 텍스트 | 2,583 | 8,782 | 18,335 | 3844 |

### Published-date timeline (15 months covered)

| month | docs |
|---|---|
| 2021-10 | 1 |
| 2023-06 | 1 |
| 2024-02 | 1 |
| 2024-03 | 4 |
| 2024-04 | 15 |
| 2024-05 | 17 |
| 2024-06 | 14 |
| 2024-07 | 3 |
| 2024-08 | 8 |
| 2024-09 | 5 |
| 2024-10 | 10 |
| 2024-11 | 7 |
| 2024-12 | 5 |
| 2025-01 | 6 |
| 2025-02 | 3 |

## Axis 2 — Chunk / index health

- total chunks: **24,862**
- by format: `hwp`=24846, `pdf`=16
- length p50 / p95 / max: **470 / 517 / 520** chars
- empty / near-empty (<50): 0 / 49
- mid-sentence cut ratio: **0.634**
- HWP native table chunks: 0 (ratio of HWP chunks: 0.000)

### Per-document chunk count

| n_docs | min | p50 | p95 | max | mean |
|---|---|---|---|---|---|
| 100 | 1 | 235.0 | 400.2 | 557 | 248.6 |

### Chunk length by file format

| format | count | p50 | p95 | max | mean |
|---|---|---|---|---|---|
| hwp | 24846 | 470 | 517 | 520 | 431 |
| pdf | 16 | 482 | 509 | 510 | 443 |

## Axis 3 — `text_source` fallback distribution

- total chunks: 24,862 across 100 docs

### Doc-level (one row per document)

| format | `data_list_csv_text` | `kordoc` | total |
|---|---|---|---|
| hwp | 0 | 96 | 96 |
| pdf | 4 | 0 | 4 |

### Chunk-level (one row per chunk)

| format | `data_list_csv_text` | `kordoc` | total |
|---|---|---|---|
| hwp | 0 | 24846 | 24846 |
| pdf | 16 | 0 | 16 |

## Axis 4 — Eval cross-decomposition

### Baseline `by_query_type` (from `baseline.aggregate.json`)

| query_type | n | abstention | accuracy | answer_format_compliance | groundedness |
|---|---|---|---|---|---|
| abstention | 4 | 0.500 | — | 0.500 | 0.500 |
| comparison | 1 | — | 1.000 | 1.000 | 1.000 |
| follow_up | 4 | — | 0.250 | 0.500 | 0.250 |
| single_doc | 12 | — | 0.500 | 0.333 | 0.500 |

_eval_summary.case_results not available locally_

## Figures

- `real100_chunks_length_box.png`
- `real100_chunks_length_box.svg`
- `real100_chunks_per_doc_hist.png`
- `real100_chunks_per_doc_hist.svg`
- `real100_eval_cross.png`
- `real100_eval_cross.svg`
- `real100_meta_agency_topN.png`
- `real100_meta_agency_topN.svg`
- `real100_meta_budget_loghist.png`
- `real100_meta_budget_loghist.svg`
- `real100_meta_timeline.png`
- `real100_meta_timeline.svg`
- `real100_text_source_stacked.png`
- `real100_text_source_stacked.svg`

