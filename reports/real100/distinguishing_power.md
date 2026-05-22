# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)

`num_predictions = 221` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`

Per ADR 0053 §Consequences:
> PR-5b's `scripts/distinguishing_power.py` can compute `(default - floor) / (ceiling - floor)` for every leaderboard metric — a single-number 'is the signal alive' gauge.

## Ablation raw values

| metric | full | random_retrieval | single_chunk |
|---|---:|---:|---:|
| accuracy | 16.10% | 2.54% | 6.78% |
| groundedness | 19.49% | 2.54% | 9.32% |
| citation_precision | 10.45% | 0.00% | 4.24% |
| claim_citation_alignment | 94.51% | 88.24% | 93.35% |
| answer_format_compliance | 13.57% | 15.28% | 42.99% |

## Per-run abstention transparency (ADR 0054)

| run | num_predictions | abstention_rate (unanswerable subset) | effective_n (substantive attempts) |
|---|---:|---:|---:|
| full | 221 | 26.21% | 118 |
| random_retrieval | 221 | 89.32% | 118 |
| single_chunk | 221 | 6.80% | 118 |

## Gauge — default vs floors

| metric | default | gap vs random | normalized vs random | gap vs single_chunk | normalized vs single_chunk | signal alive |
|---|---:|---:|---:|---:|---:|:---:|
| accuracy | 16.10% | +13.56pp | 13.91% | +9.32pp | 10.00% | yes |
| groundedness | 19.49% | +16.95pp | 17.39% | +10.17pp | 11.21% | yes |
| citation_precision | 10.45% | +10.45pp | 10.45% | +6.21pp | 6.49% | yes |
| claim_citation_alignment | 94.51% | +6.27pp | 53.32% | +1.16pp | 17.41% | yes |
| answer_format_compliance | 13.57% | -1.71pp | -2.02% | -29.42pp | -51.61% | no |

## Verdict

- **accuracy**: signal alive — default beats both floors (+13.56pp vs random, +9.32pp vs single_chunk).
- **groundedness**: signal alive — default beats both floors (+16.95pp vs random, +10.17pp vs single_chunk).
- **citation_precision**: signal alive — default beats both floors (+10.45pp vs random, +6.21pp vs single_chunk).
- **claim_citation_alignment**: signal alive — default beats both floors (+6.27pp vs random, +1.16pp vs single_chunk).
- **answer_format_compliance**: ⚠️ signal NOT alive — default does not beat both floors (-1.71pp vs random, -29.42pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.

_Aggregate-only per ADR 0005. No per-case data is read by this script._
