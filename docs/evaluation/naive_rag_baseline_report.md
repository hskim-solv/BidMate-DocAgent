# Naive RAG Smoke/Regression Report

> **Warning:** CI smoke/regression 전용입니다. 이 공개 fixture 결과의 Recall@5, Recall@10, MRR@5, nDCG@5, `rule_based_groundedness`, `term_coverage_accuracy`, `generator_hallucination_rate`, P95 latency는 RAG 성능(performance) claim에 사용할 수 없습니다.

이 문서는 기존 public fixture eval을 보존하되, 목적을 명확히 낮춘 smoke/regression report입니다. 실제 naive RAG benchmark는 [`naive_rag_benchmark_v1.md`](naive_rag_benchmark_v1.md)와 `configs/eval/benchmark_naive_rag_v1.yaml`에서 별도로 다룹니다.

## Evaluation Command

```bash
python3 eval/run_eval.py --config experiments/runs/naive_baseline_20260524T054514Z/config.naive.yaml --index_dir data/index --output_dir experiments/runs/naive_baseline_20260524T054514Z
```

## Run Metadata

- run_id: `naive_baseline_20260524T054514Z`
- evaluation type: `public_fixture_smoke_regression`
- dataset size: 5
- answerable questions: 4
- unanswerable questions: 1
- fixture corpus: 5 documents / 6 chunks
- naive top_k: 5 in the runtime preset inspected by the audit
- chunk_count/top_k ratio: 1.2
- gold evidence source: 0 explicit, 4 derived from `expected_doc_ids` + `expected_terms`
- latency scope: warm in-process fixture query latency only; ingestion, parsing, chunking, embedding/index build, index loading, and LLM generation are excluded

## Metric Summary (Smoke Only)

| System | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | citation_chunk_accuracy | rule_based_groundedness | term_coverage_accuracy | generator_hallucination_rate | failed_abstention_rate | Warm P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Naive Dense RAG | 1.000 | 1.000 | 1.000 | 1.000 | 0.875 | 1.000 | 1.000 | 0.000 | 1.000 | 2.52 ms |

## Metric Semantics

- Retrieval metrics use exact `chunk_id` equality, but this smoke fixture has only 6 chunks and derived gold labels, so Recall/MRR/nDCG are regression signals only.
- `rule_based_groundedness` is a rule-based placeholder over retrieved/cited chunks, not semantic Faithfulness.
- `term_coverage_accuracy` is expected-term containment, not semantic Answer Relevancy.
- `generator_hallucination_rate` counts only generator hallucination failures; failed abstention is surfaced separately as `failed_abstention_rate`.
- `citation_chunk_accuracy` is chunk/doc citation precision. It is not page-level or support-span citation accuracy.
- Missing page metadata is a headline smoke finding, not a minor note: the inspected run had page metadata missing on all fixture chunks.

## Failure Categories

### Retrieval Failures

- gold evidence not in top-k: 0
- gold evidence ranked too low: 0
- wrong similar clause: 0
- chunk boundary split: 0
- query wording mismatch: 0
- multi-chunk evidence missing: 0

### Parsing And Citation Metadata Failures

- page metadata missing: 5
- missing page number: 5
- correct answer but wrong citation: 1

### Answer Failures

- failed to abstain: 1
- generator hallucination: 0

## Interpretation

Trustworthy from this smoke report:

- The public fixture path invokes the real `run_rag_query()` path.
- The smoke artifact is reproducible and useful for CI regression stability.
- The run visibly exposes failed abstention and missing page metadata.

Not trustworthy for performance claims:

- Retrieval quality over real corpora.
- Semantic answer quality, Faithfulness, or Answer Relevancy.
- Overall hallucination/unsafe answer rate unless failed abstention is included.
- Product or end-to-end latency.

## Next Step

Use the separate benchmark seed and sanity runner before any RAG performance optimization:

```bash
python3 -m eval.naive_rag.benchmark --config configs/eval/benchmark_naive_rag_v1.yaml
```
