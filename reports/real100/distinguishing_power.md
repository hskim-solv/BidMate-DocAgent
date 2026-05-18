# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)

`num_predictions = 221` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`

Per ADR 0053 §Consequences:
> PR-5b's `scripts/distinguishing_power.py` can compute `(default - floor) / (ceiling - floor)` for every leaderboard metric — a single-number 'is the signal alive' gauge.

## Ablation raw values

| metric | full | random_retrieval | single_chunk |
|---|---:|---:|---:|
| accuracy | 29.66% | 2.54% | 6.78% |
| groundedness | 33.90% | 2.54% | 9.32% |
| citation_precision | 22.06% | 0.00% | 4.24% |
| claim_citation_alignment | 96.28% | 88.24% | 93.35% |
| answer_format_compliance | 14.63% | 15.28% | 42.99% |

## Per-run abstention transparency (ADR 0054)

| run | num_predictions | abstention_rate (unanswerable subset) | effective_n (substantive attempts) |
|---|---:|---:|---:|
| full | 221 | 15.53% | 118 |
| random_retrieval | 221 | 89.32% | 118 |
| single_chunk | 221 | 6.80% | 118 |

## Gauge — default vs floors

| metric | default | gap vs random | normalized vs random | gap vs single_chunk | normalized vs single_chunk | signal alive |
|---|---:|---:|---:|---:|---:|:---:|
| accuracy | 29.66% | +27.12pp | 27.83% | +22.88pp | 24.55% | yes |
| groundedness | 33.90% | +31.36pp | 32.17% | +24.58pp | 27.10% | yes |
| citation_precision | 22.06% | +22.06pp | 22.06% | +17.82pp | 18.61% | yes |
| claim_citation_alignment | 96.28% | +8.04pp | 68.35% | +2.93pp | 44.00% | yes |
| answer_format_compliance | 14.63% | -0.64pp | -0.76% | -28.36pp | -49.74% | no |

## Verdict

- **accuracy**: signal alive — default beats both floors (+27.12pp vs random, +22.88pp vs single_chunk).
- **groundedness**: signal alive — default beats both floors (+31.36pp vs random, +24.58pp vs single_chunk).
- **citation_precision**: signal alive — default beats both floors (+22.06pp vs random, +17.82pp vs single_chunk).
- **claim_citation_alignment**: signal alive — default beats both floors (+8.04pp vs random, +2.93pp vs single_chunk).
- **answer_format_compliance**: ⚠️ signal NOT alive — default does not beat both floors (-0.64pp vs random, -28.36pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.

_Aggregate-only per ADR 0005. No per-case data is read by this script._
