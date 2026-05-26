# Plan: T-2026-0001 Benchmark Contamination Guard

- Status: done
- Owner role: Implementer
- Related task: `tasks/queue.md::T-2026-0001`
- Related issue / PR: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480) / [#1481](https://github.com/hskim-solv/BidMate-DocAgent/pull/1481)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

The public synthetic benchmark already uses explicit gold evidence, but the
validator report did not expose a machine-readable proof that the benchmark
index build is corpus-only. Future benchmark claims need reviewer-visible
evidence that questions, expected answers, and gold labels are not index input.

## Desired Behavior

`validate_benchmark_dataset.py` reports an `index_build_boundary` block showing
that `index_build.input_path` equals `corpus_path`, the command builds from
`--corpus`, and corpus chunk rows contain no query/gold label fields.

## Constraints

- Do not change benchmark scoring semantics.
- Do not change retrieval, verifier, answer, or private real-eval behavior.
- Keep the surface classified as public synthetic benchmark only.

## Architecture Impact

- Affected modules: benchmark dataset validator and focused benchmark tests.
- Load-bearing paths: `eval/`.
- ADR required: no, this hardens an existing surface without changing its meaning.
- Backward compatibility: additive report fields only.

## Validation Strategy

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json

python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
```

## Reviewer Notes

Attack the corpus-only proof first: the validator must fail if `index_build`
points at questions/gold input or if corpus chunks carry label fields.
