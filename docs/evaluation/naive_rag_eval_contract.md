# Naive RAG Evaluation Contract

## TL;DR

- 이 문서는 `naive_baseline`의 성능을 개선하지 않고, 현재 기준선(baseline)을 측정 가능하게 만드는 평가(evaluation) 계약(contract)이다.
- 실행 명령은 `python -m eval.naive_rag.run_eval --config configs/eval/rag_quality_v1.yaml`이다.
- 출력은 `experiments/runs/<run_id>/` 아래에 저장되며, 검색(retrieval) 지표와 답변(answer) 지표를 분리한다.

## Current Evidence Boundary

This contract is a public-fixture/local-run evaluation contract, not a private
performance claim surface. New private-eval task, PR, claim, and handoff
evidence must use `real100_v2` aggregate-only evidence with matching provenance;
legacy `real100` / v1 / 221-case / `kordoc` evidence remains archive-only unless
the maintainer explicitly re-enables another private-eval surface.

## 목적

이 계약은 RFP/document QA RAG 시스템에서 후속 개선을 비교하기 위한 첫 기준선을 고정한다. 재순위(reranking), hybrid 검색(retrieval), 메타데이터 필터링(metadata filtering), query rewriting, self-correction, agentic retrieval을 붙이기 전에 naive RAG가 무엇을 맞히고 어디서 실패하는지 기록한다.

## Naive Baseline 범위

포함:

- text-only 추출로 만들어진 기존 index 사용
- fixed-size overlapping chunking 결과 사용
- dense vector top-k 검색(retrieval)
- top-k chunk를 그대로 답변(answer) 컨텍스트로 전달
- 단순 source reference: `chunk_id`, `doc_id`, 있으면 `page_span`

제외:

- 재순위(reranking)
- hybrid BM25 + dense 검색(retrieval)
- 메타데이터 필터링(metadata filtering)
- query rewriting / HyDE
- query decomposition
- layout-aware parsing
- table/figure-specific handling
- VLM grounding
- citation verifier
- self-correction loop
- abstention classifier
- RAG 성능 개선 목적의 prompt tuning

## 실행

```bash
python -m eval.naive_rag.run_eval --config configs/eval/rag_quality_v1.yaml
```

재현 가능한 run id가 필요하면:

```bash
python -m eval.naive_rag.run_eval \
  --config configs/eval/rag_quality_v1.yaml \
  --run-id local-check
```

## 입력 데이터

Config:

- `configs/eval/rag_quality_v1.yaml`
- `pipeline.name: naive_baseline`
- `pipeline.top_k: 10`
- `pipeline.retrieval_backend: dense`
- `metadata_first`, `rerank`, `verifier_retry`는 모두 `false`
- `query_expansion: identity`

Questions:

- `data/eval/rag_questions.jsonl`
- 필수 필드: `question_id`, `question`, `answerable`
- 권장 필드: `query_type`, `expected_answer`, `expected_terms`

Gold evidence:

- `data/eval/gold_evidence.jsonl`
- 각 row는 `question_id`와 `gold_evidence[]`를 가진다.
- answerable 질문은 `gold_evidence[].chunk_id`가 기존 `data/index/index.json`의 chunk id를 가리킨다.
- unanswerable 질문은 `gold_evidence: []`를 사용한다.

샘플 세트는 public fixture 기반이며 answerable 13개, unanswerable 3개를 포함한다. 비공개 RFP 데이터는 사용하지 않는다.

## 출력

Runner는 `experiments/runs/<run_id>/` 아래에 다음 파일을 쓴다.

- `metrics.json` - run metadata, dataset counts, 검색(retrieval) 지표, 답변(answer) 지표, failure counts
- `retrieved_chunks.jsonl` - 질문별 retrieved chunk ranks, scores, gold ids
- `answers.jsonl` - 질문별 answer text, citations, per-case metrics
- `failure_cases.jsonl` - 실패 케이스와 `failure_type`
- `summary.md` - 사람이 읽는 run summary

`experiments/runs/`는 `.gitignore` 대상이다. 계약(config), 샘플 데이터(sample data), 문서(docs), 테스트(tests)만 PR에 포함한다.

## Metrics

검색(retrieval) 지표:

- `recall_at_5`: gold chunk 중 top5 안에 들어온 비율
- `recall_at_10`: gold chunk 중 top10 안에 들어온 비율
- `mrr_at_5`: top5 안 첫 gold chunk의 reciprocal rank
- `ndcg_at_5`: binary relevance 기반 nDCG@5

답변(answer) 지표:

- `faithfulness`: citation chunk가 retrieved evidence 안에 있는지 보는 placeholder 지표
- `answer_relevancy`: `expected_terms`가 answer text에 포함된 비율
- `citation_accuracy`: citation chunk 중 gold chunk에 해당하는 비율
- `hallucination_flag`: unanswerable 답변 생성 또는 gold와 무관한 supported citation 여부
- `unanswerable_detection_flag`: unanswerable 질문에서 `insufficient` 또는 abstained 상태가 나왔는지

이 답변 지표들은 simple/placeholder이다. LLM judge, verifier, citation verifier, RAGAS류 평가는 이 계약의 범위 밖이다.

## Failure Taxonomy

Failure case row는 최소 하나의 `failure_type`을 가진다. 현재 deterministic classifier는 관측 가능한 신호만 라벨링하고, 전체 taxonomy는 후속 failure analysis를 위해 고정한다.

Retrieval failures:

- `retrieval_failure.gold_evidence_not_in_top_k`
- `retrieval_failure.gold_evidence_ranked_too_low`
- `retrieval_failure.wrong_similar_clause`
- `retrieval_failure.chunk_boundary_split`
- `retrieval_failure.query_wording_mismatch`
- `retrieval_failure.multi_chunk_evidence_missing`

Parsing failures:

- `parsing_failure.table_content_lost`
- `parsing_failure.figure_content_ignored`
- `parsing_failure.page_metadata_missing`
- `parsing_failure.header_footer_noise`
- `parsing_failure.korean_english_mixed_text_issue`

Citation failures:

- `citation_failure.correct_answer_wrong_citation`
- `citation_failure.insufficient_citation`
- `citation_failure.missing_page_number`
- `citation_failure.citation_does_not_support_claim`
- `citation_failure.vague_citation_for_multiple_claims`

Answer failures:

- `answer_failure.hallucinated_requirement`
- `answer_failure.partial_answer`
- `answer_failure.overconfident_weak_evidence`
- `answer_failure.wrong_synthesis`
- `answer_failure.failed_to_abstain`

Evaluation failures:

- `evaluation_failure.no_gold_evidence`
- `evaluation_failure.metric_missing`
- `evaluation_failure.failure_case_not_saved`

## Intentional Non-Goals

- 검색(retrieval) 품질을 높이지 않는다.
- chunking strategy를 바꾸지 않는다.
- `naive_baseline` preset 기본값을 바꾸지 않는다.
- 기존 `eval/run_eval.py`의 aggregate surface를 대체하지 않는다.
- private/internal eval claim을 만들지 않는다.
