# Naive RAG Benchmark v1

## TL;DR

- `naive_rag_benchmark` v1 is a public-synthetic benchmark for finding Naive RAG retrieval, citation, and abstention failures before optimization work.
- It is separate from `public_fixture_smoke_regression` and is not a CI smoke eval.
- Gold evidence is explicit in `gold_evidence_v1.jsonl`; retrieval metrics must not be derived from `expected_terms`.

## Paths

| artifact | path |
|---|---|
| config | `configs/eval/benchmark_naive_rag_v1.yaml` |
| corpus chunks | `data/eval/benchmark/corpus_chunks_v1.jsonl` |
| questions | `data/eval/benchmark/rag_questions_v1.jsonl` |
| gold evidence | `data/eval/benchmark/gold_evidence_v1.jsonl` |
| benchmark index | `data/eval/benchmark/index_v1` |
| results report | `docs/evaluation/naive_rag_benchmark_v1_results.md` |

## Build Index

```bash
python3 -m eval.naive_rag.build_benchmark_index \
  --corpus data/eval/benchmark/corpus_chunks_v1.jsonl \
  --output data/eval/benchmark/index_v1
```

The index builder reads only `corpus_chunks_v1.jsonl`. It must not read questions, gold evidence, expected answers, or expected terms.

## Run Benchmark

```bash
python3 -m eval.naive_rag.benchmark \
  --config configs/eval/benchmark_naive_rag_v1.yaml
```

Outputs are written to `experiments/runs/<run_id>/`:

- `metrics.json`
- `retrieved_chunks.jsonl`
- `answers.jsonl`
- `failure_cases.jsonl`
- `summary.md`

## Interpretation

Retrieval metrics are computed from explicit gold evidence chunk ids. Citation/page and answer metrics are rule-based/provisional. Do not report them as semantic faithfulness or semantic answer relevancy.

This benchmark is useful for failure discovery and ablation setup, not production-level performance claims.
