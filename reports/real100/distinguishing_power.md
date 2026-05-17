# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)

`num_predictions = 221` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`

Per ADR 0053 §Consequences:
> PR-5b's `scripts/distinguishing_power.py` can compute `(default - floor) / (ceiling - floor)` for every leaderboard metric — a single-number 'is the signal alive' gauge.

## Ablation raw values

| metric | full | random_retrieval | single_chunk |
|---|---:|---:|---:|
| accuracy | 29.66% | 2.54% | 6.78% |
| groundedness | 25.34% | 36.20% | 8.14% |
| citation_precision | 19.02% | 34.84% | 5.43% |
| claim_citation_alignment | 96.28% | 88.24% | 93.35% |
| answer_format_compliance | 20.81% | 44.80% | 44.80% |

## Gauge — default vs floors

| metric | default | gap vs random | normalized vs random | gap vs single_chunk | normalized vs single_chunk | signal alive |
|---|---:|---:|---:|---:|---:|:---:|
| accuracy | 29.66% | +27.12pp | 27.83% | +22.88pp | 24.55% | yes |
| groundedness | 25.34% | -10.86pp | -17.02% | +17.19pp | 18.72% | no |
| citation_precision | 19.02% | -15.82pp | -24.28% | +13.59pp | 14.37% | no |
| claim_citation_alignment | 96.28% | +8.04pp | 68.35% | +2.93pp | 44.00% | yes |
| answer_format_compliance | 20.81% | -23.98pp | -43.44% | -23.98pp | -43.44% | no |

## Verdict

- **accuracy**: signal alive — default beats both floors (+27.12pp vs random, +22.88pp vs single_chunk).
- **groundedness**: ⚠️ signal NOT alive — default does not beat both floors (-10.86pp vs random, +17.19pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.
- **citation_precision**: ⚠️ signal NOT alive — default does not beat both floors (-15.82pp vs random, +13.59pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.
- **claim_citation_alignment**: signal alive — default beats both floors (+8.04pp vs random, +2.93pp vs single_chunk).
- **answer_format_compliance**: ⚠️ signal NOT alive — default does not beat both floors (-23.98pp vs random, -23.98pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.

_Aggregate-only per ADR 0005. No per-case data is read by this script._
