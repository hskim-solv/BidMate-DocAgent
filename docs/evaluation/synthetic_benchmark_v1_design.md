# Synthetic Naive RAG Benchmark v1 Design

## TL;DR

- `synthetic_naive_rag_benchmark_v1`은 Naive RAG의 약점을 공개 재현 가능한 방식으로 드러내기 위한 benchmark이다.
- 이 benchmark는 smoke eval이 아니며, private real-eval을 대체하지 않는다.
- 성능 개선을 주장하기 전에 데이터셋 검증, index build, 첫 naive baseline 측정을 순서대로 실행한다.

## Purpose

이 benchmark의 목적은 재순위(reranking), hybrid 검색(retrieval), citation verifier, abstention control 같은 최적화 전에 Naive RAG가 어디서 실패하는지 관측하는 것이다. 목표 failure mode는 wrong similar clause retrieval, gold evidence not in top-k, gold evidence ranked too low, multi-chunk evidence missing, weak citation support, failed abstention, table confusion, Korean/English mixed wording mismatch이다.

## Why Synthetic Data

공개 저장소에서 반복 가능한 benchmark가 필요하지만 실제 RFP 문서는 비공개·권리·보안 제약이 있다. 그래서 문서, 일정, 기관명, 요구사항을 모두 synthetic-public으로 작성했다. 각 corpus 문서는 `document_type: synthetic_public_benchmark_v1`와 `synthetic: true` metadata를 가진다.

Synthetic data는 failure probe와 ablation 준비에는 유용하지만 실제 조달 문서의 분포, noise, 서식, 기관별 관행을 완전히 대표하지 않는다. 최종 real-world baseline claim은 private real-eval에서만 해야 한다.

## Dataset Composition

- Corpus path: `data/eval/benchmark/corpus/`
- Corpus chunks: `data/eval/benchmark/corpus_chunks_v1.jsonl`
- Config: `configs/eval/benchmark_naive_rag_v1.yaml`
- Questions: `data/eval/benchmark/rag_questions_v1.jsonl`
- Gold evidence: `data/eval/benchmark/gold_evidence_v1.jsonl`
- Benchmark index path: `data/eval/benchmark/index_v1/`
- Documents: 6 synthetic RFP-style documents
- Chunks: 72 section chunks
- Questions: 55 total, 40 answerable and 15 unanswerable
- Gold evidence records: 47 explicit records for 40 answerable questions

Question type distribution:

| question_type | count |
|---|---:|
| `exact_fact` | 10 |
| `similar_clause_disambiguation` | 8 |
| `multi_chunk_synthesis` | 7 |
| `table_structured_data` | 5 |
| `date_amount_score_extraction` | 5 |
| `mixed_language` | 5 |
| `unanswerable` | 15 |

## Distractor Design

The corpus intentionally repeats similar terms across nearby sections:

- proposal submission deadline vs Q&A deadline
- technical proposal deadline vs price proposal deadline
- technical evaluation score vs price evaluation score
- maintenance period vs project period
- cloud security requirement vs general security requirement
- deliverable submission date vs final inspection date
- required personnel count vs recommended personnel count
- mandatory requirement vs recommended requirement

Similar-clause and hard questions use `distractor_sensitive: true` when the expected failure depends on these near misses.

## Gold Evidence Rules

- Gold evidence is manually specified in `gold_evidence_v1.jsonl`.
- Gold evidence is never derived from `expected_terms`; benchmark questions do not rely on `expected_terms` for evidence selection.
- Every answerable question has one or more `expected_evidence_ids`.
- Every `expected_evidence_id` must exist as an `evidence_id` in the gold file.
- Unanswerable questions must have no gold evidence.
- Multi-chunk questions must have more than one required gold evidence record.
- `support_text` must appear in the synthetic corpus and in the configured chunk when `chunk_id` is present.

Supported `support_type` values are `exact_span`, `table_cell`, `multi_chunk`, and `section`.

## Leakage Prevention

Questions should not simply copy support sentences. Some lexical overlap is unavoidable for dates, amounts, scores, and named technical terms. The validator therefore reports leakage risk instead of blocking all overlap.

The leakage report compares:

- question text vs support_text
- expected_answer vs support_text

It flags direct substrings, high token containment, and high overlap for hard questions. Treat this as an iterative curation signal, not as a semantic quality score.

## Validation

Run:

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json
```

The report path is local generated output. It includes dataset counts, question type distribution, gold evidence summary, page metadata coverage, chunk_count/top_k ratio, warnings, errors, and lexical leakage flags.

## Build Benchmark Index

Run:

```bash
python3 -m eval.naive_rag.build_benchmark_index \
  --corpus data/eval/benchmark/corpus_chunks_v1.jsonl \
  --output data/eval/benchmark/index_v1
```

This index is built only from frozen corpus chunks. It must not read questions, gold evidence, expected answers, or expected terms. It is separate from the smoke fixture index at `data/index/`, and the benchmark config must not point to the smoke fixture index.

## Run Benchmark

Run:

```bash
python3 -m eval.naive_rag.benchmark \
  --config configs/eval/benchmark_naive_rag_v1.yaml
```

This command runs dense top-k retrieval only. It does not enable reranking, hybrid BM25+dense fusion, metadata-first retrieval, query expansion, verifier retry, self-correction, or prompt tuning.

## Safe Interpretation

Use this benchmark for public reproducibility, ablation setup, and failure-mode discovery. Do not use it as final evidence of production RAG quality. In particular:

- Perfect scores on this synthetic benchmark do not imply real RFP performance.
- The answer metrics are rule-based/provisional lexical and citation checks, not semantic RAGAS-style judges.
- Retrieval failures are more meaningful than headline answer quality until semantic judging or verifier-backed scoring is added.
- Private real-eval remains required for credible real-world baseline claims.

## Known Limitations

- The corpus is synthetic and cleaner than many real procurement documents.
- Section chunking makes gold annotation stable, but it does not fully reproduce OCR, PDF table, or mid-sentence chunk-boundary noise.
- Leakage warnings remain in the dataset because date, amount, score, and table questions necessarily share some tokens with support spans.
- Korean/English mixed wording is represented with explicit technical terms, but real documents may contain more inconsistent spacing, abbreviations, and formatting.
- The committed benchmark does not claim a RAG performance improvement; it only hardens the measurement surface.
