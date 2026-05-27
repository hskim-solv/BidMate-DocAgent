# real100_v2 Baseline Refresh Packet

Issue: [#1618](https://github.com/hskim-solv/BidMate-DocAgent/issues/1618)  
Task: `T-2026-0028`  
Status: aggregate-only v2 evidence packet; no performance-improvement claim.

## Decision

Use `real100_v2` only for current private eval evidence. Legacy `real100`/v1,
221-case aggregates, and kordoc/v1 index evidence are banned for new tasks,
PRs, claims, and handoffs until the maintainer explicitly re-enables them.

Next task decision: **no-go for claim-bearing retrieval or page/citation work
until v2 page metadata is repaired or explicitly scoped out**. `T-2026-0029`
may proceed only as diagnostic work that treats v2 page metadata absence as a
known blocker; do not use old `real100` evidence to fill the gap.

## Sources

All sources are committed aggregate-only artifacts:

- `reports/real100_v2/baseline.aggregate.json`
- `reports/real100_v2/question_distribution.aggregate.json`
- `reports/real100_v2/parse_inventory.aggregate.json`
- `reports/real100_v2/benchmark_tiers.aggregate.json`
- `reports/real100_v2/metric_suite.aggregate.json`

Raw eval summaries, traces, questions, answers, evidence, document IDs, chunk
IDs, filenames, paths, parsed Markdown, converted PDFs, and per-case rows remain
outside this packet.

## Aggregate Snapshot

| Surface | Value |
|---|---:|
| Profile | `private_real100_v2_baseline` |
| Predictions | 300 |
| Documents | 100 |
| Chunks | 21,800 |
| Answerable / unanswerable | 272 / 28 |
| Single-chunk / multi-chunk / no-gold | 232 / 40 / 28 |
| Query types | 259 single-doc, 13 comparison, 28 abstention |
| Page metadata ready rate | 0.0 |
| Markdown exports | 100 |

## Metrics

| Metric | Aggregate |
|---|---:|
| Recall@5 | 0.3695 |
| Recall@10 | 0.4338 |
| MRR@5 | 0.2567 |
| nDCG@5 | 0.2826 |
| Citation precision | 0.1463 |
| Groundedness | 0.7757 |
| Claim-citation alignment | 0.8911 |
| Abstention | 0.3929 |
| Mean latency ms | 2206.35 |
| p95 latency ms | 3199.06 |

These are baseline/provenance readings only. They are not a paired delta and do
not support a performance-improvement claim.

## Failure / Readiness Notes

- Dominant aggregate failure signal: `parse_or_metadata_issue` count 193.
- Verifier false negative count: 17.
- Verifier false positive count: 2.
- Page metadata ready count: 0 / 21,800 chunks.
- Metric suite status: 7 present, 1 partial, 0 missing; human judge agreement is
  partial and requires approved aggregate input.

## Validation Summary

Executed:

```bash
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check
make real-eval-v2-guard
make real-eval
```

Results:

- `real-eval-v2-check`: passed; v2 config, data list, documents, index,
  report dir, eval summary, and baseline summary are present.
- `real-eval-v2-guard`: passed after policy/guard updates.
- `make real-eval`: intentionally failed with exit code 2 because legacy v1
  private eval targets are disabled.

Not executed:

- Default `make real-eval`, `make real-eval-minilm`, and `make
  real-eval-semantic` as baseline runs. They are now fail-closed legacy targets.
- Paired delta. No comparable v2 base/head pair was produced in this task.

## Privacy Boundary

The source artifacts state `aggregate_only: true` and omit raw questions,
answers, evidence, text, filenames, local paths, document IDs, chunk IDs, and
per-case rows. This packet repeats only aggregate counts, metrics, provenance
class, and policy decisions.
