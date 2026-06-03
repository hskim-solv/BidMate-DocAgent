# real100_v2 Benchmark Tier Split

Issue: [#1503](https://github.com/hskim-solv/BidMate-DocAgent/issues/1503)  
Surface: private real-eval aggregate-only interpretation.

## Purpose

`reports/real100_v2/benchmark_tiers.aggregate.json` separates the private
`real100_v2` aggregate into three interpretation tiers so reviewers can read a
run as more than one headline average:

- `easy_sanity` — answerable, single-doc / single-chunk checks with clear terms.
- `standard_real` — normal RFP QA such as date, amount, score, schedule, or
  requirement extraction with moderate distractors.
- `hard_stress` — multi-chunk, multi-doc, table-heavy, similar-clause,
  unanswerable, citation/page-dependent, or parser-stress cases.

The split is for interpretation and regression analysis only. It is not a
license to cherry-pick a winning tier while hiding the overall result or another
regressing tier.

## Renderer

The aggregate is produced by:

```bash
python3 scripts/render_real100_v2_aggregates.py \
  --eval-summary <private-local-real100_v2-eval-summary.json> \
  --questions <private-local-real100_v2-questions.jsonl> \
  --baseline-out reports/real100_v2/baseline.aggregate.json \
  --tiers-out reports/real100_v2/benchmark_tiers.aggregate.json
```

Inputs may be private local files. Only allowlisted aggregate output may be
committed.

## Commit Boundary

Committed tier artifacts must omit raw questions, answers, evidence text,
filenames, local paths, `doc_id`, `chunk_id`, and per-case rows. The renderer
emits only tier names, counts, aggregate metric means, missing counts,
abstention outcome counts, and safe failure-category counts.

## Claim Rules

Allowed:

- “The private `real100_v2` aggregate improved or regressed in tier X” when the
  same report also names the overall result, every tier, config/index
  provenance, and paired-delta context.
- “Tier X is the dominant stress slice for this run” when stated as diagnostic
  interpretation, not as a global quality claim.

Disallowed:

- Using one improved tier as a headline while another tier or the overall
  aggregate regresses.
- Mixing legacy `real100`/v1/221/kordoc evidence into a current `real100_v2`
  tier claim.
- Committing raw private case rows to explain a tier.

## Regression Guard

`tests/test_render_real100_v2_aggregates.py` locks the renderer contract with
synthetic fixtures and checks that both generated and committed aggregate tier
artifacts stay public-safe.
