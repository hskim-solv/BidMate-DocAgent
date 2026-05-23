# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)

`num_predictions = 221` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`

source: `fa6ebd2002b5` (git_dirty=False) · generated_at 2026-05-23T02:41:36.889094Z

`signal` is CI-aware (ADR 0053 amendment, issue #1367): `alive` only when the default's 95% CI is strictly above **both** floors' CIs; a positive point gap with overlapping CI is `uncertain`, not `alive`.

Per ADR 0053 §Consequences:
> PR-5b's `scripts/distinguishing_power.py` can compute `(default - floor) / (ceiling - floor)` for every leaderboard metric — a single-number 'is the signal alive' gauge.

## Ablation raw values

| metric | full | random_retrieval | single_chunk |
|---|---:|---:|---:|
| accuracy | 16.10% (n=118) | 2.54% (n=118) | 6.78% (n=118) |
| groundedness | 19.49% (n=118) | 2.54% (n=118) | 9.32% (n=118) |
| citation_precision | 10.45% (n=118) | 0.00% (n=118) | 4.24% (n=118) |
| claim_citation_alignment | 94.10% (n=161) | 88.00% (n=50) | 93.35% (n=188) |
| answer_format_compliance | 12.04% (n=191) | 16.06% (n=137) | 42.99% (n=214) |

_Per-cell `n` = CI denominator for that (metric, run). Quality metrics (`accuracy` / `groundedness` / `citation_precision`) are conditional on a substantive answer attempt (ADR 0054) and so share the smaller `effective_n` below. `answer_format_compliance` and `claim_citation_alignment` stay measurable on over-answered / answered cases (format and alignment need no gold), so their `n` is larger and differs per run — disclosed per-cell here, not folded into one denominator. Each `gap vs floor` therefore compares means on per-metric denominators, not a single shared `n`._

## Per-run abstention transparency (ADR 0054)

| run | num_predictions | abstention_rate (unanswerable subset) | effective_n (≈ accuracy/groundedness/citation_precision denom) |
|---|---:|---:|---:|
| full | 221 | 33.98% | 118 |
| random_retrieval | 221 | 96.12% | 118 |
| single_chunk | 221 | 6.80% | 118 |

## Gauge — default vs floors (CI-aware)

| metric | default | default 95% CI | gap vs random | CI-sep vs random | gap vs single_chunk | CI-sep vs single_chunk | signal |
|---|---:|---:|---:|:---:|---:|:---:|:---:|
| accuracy | 16.10% | [9.3, 22.9] | +13.56pp | yes | +9.32pp | no | uncertain |
| groundedness | 19.49% | [12.7, 27.1] | +16.95pp | yes | +10.17pp | no | uncertain |
| citation_precision | 10.45% | [5.9, 15.8] | +10.45pp | yes | +6.21pp | no | uncertain |
| claim_citation_alignment | 94.10% | [91.0, 96.9] | +6.10pp | no | +0.75pp | no | uncertain |
| answer_format_compliance | 12.04% | [7.3, 16.8] | -4.02pp | no | -30.95pp | no | dead |

## Verdict

- **accuracy**: ⚠️ signal uncertain — default beats both floors on the point estimate (+13.56pp vs random, +9.32pp vs single_chunk) but its 95% CI overlaps at least one floor (not CI-separated). Not yet distinguishable from noise.
- **groundedness**: ⚠️ signal uncertain — default beats both floors on the point estimate (+16.95pp vs random, +10.17pp vs single_chunk) but its 95% CI overlaps at least one floor (not CI-separated). Not yet distinguishable from noise.
- **citation_precision**: ⚠️ signal uncertain — default beats both floors on the point estimate (+10.45pp vs random, +6.21pp vs single_chunk) but its 95% CI overlaps at least one floor (not CI-separated). Not yet distinguishable from noise.
- **claim_citation_alignment**: ⚠️ signal uncertain — default beats both floors on the point estimate (+6.10pp vs random, +0.75pp vs single_chunk) but its 95% CI overlaps at least one floor (not CI-separated). Not yet distinguishable from noise.
- **answer_format_compliance**: ⚠️ signal NOT alive — default does not beat both floors (-4.02pp vs random, -30.95pp vs single_chunk). Retrieval or pipeline not pulling weight on this metric.

_Aggregate-only per ADR 0005. No per-case data is read by this script._
