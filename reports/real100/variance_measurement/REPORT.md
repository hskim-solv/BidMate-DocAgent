# Variance measurement — N=3 runs at same HEAD

Reads N `eval_summary.json` snapshots produced at the same git HEAD
+ same `eval/real_config.local.yaml`. Emits per-category mean/std/
min/max + per-case stability + transition matrix.

## 7-category run statistics

| category | values | mean | stdev | min | max | spread |
|---|---|---:|---:|---:|---:|---:|
| verifier_false_negative | 76, 76, 76 | 76 | 0.0 | 76 | 76 | 0 |
| retrieval_miss | 64, 64, 64 | 64 | 0.0 | 64 | 64 | 0 |
| unknown | 35, 35, 35 | 35 | 0.0 | 35 | 35 | 0 |
| verifier_false_positive | 3, 3, 3 | 3 | 0.0 | 3 | 3 | 0 |
| planner_under_decomposition | 1, 1, 1 | 1 | 0.0 | 1 | 1 | 0 |
| generator_hallucination | 1, 1, 1 | 1 | 0.0 | 1 | 1 | 0 |
| context_dilution | 0, 0, 0 | 0 | 0.0 | 0 | 0 | 0 |

## ADR 0059 first-match contract per run

`failure_category_counts.verifier_false_negative == abstention_outcomes.incorrect_answer`

| run | vfn | incorrect_answer | contract |
|---|---:|---:|:---:|
| run_1.json | 76 | 76 | ✓ |
| run_2.json | 76 | 76 | ✓ |
| run_3.json | 76 | 76 | ✓ |

**All runs contract ok**: ✓

## Per-case stability

- Total cases observed: 221
- Stable (same category across all runs): 221
- Fluctuating (≥2 distinct categories): 0

**Fluctuation histogram** (distinct_count → number of cases):

| distinct categories | case count |
|---:|---:|
| 1 | 221 |

## Transition matrix (top 15)

Consecutive (run_i → run_{i+1}) category transitions on fluctuating cases.

(no transitions — all cases stable)

