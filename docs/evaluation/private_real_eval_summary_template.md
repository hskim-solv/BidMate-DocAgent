# Private Real-Eval Redacted Summary Template

이 파일은 private real-eval 결과를 공개 가능한 형태로 요약할 때의 필드 계약(contract)이다. 실제 raw 질문(question), 답변(answer), 근거(evidence), 파일명, 고객명, private path는 포함하지 않는다.

```json
{
  "schema_version": 1,
  "benchmark_type": "private_real_eval",
  "system": "Naive Dense RAG",
  "not_ci_smoke": true,
  "is_private_data": true,
  "dataset": {
    "num_documents": 100,
    "num_chunks": 25000,
    "num_questions": 221,
    "answerable_count": 180,
    "unanswerable_count": 41
  },
  "pipeline": {
    "name": "naive_baseline",
    "top_k": 10,
    "retrieval_backend": "dense",
    "metadata_first": false,
    "rerank": false,
    "verifier_retry": false,
    "query_expansion": "identity"
  },
  "metrics": {
    "retrieval": {
      "recall_at_5": {"mean": 0.0, "n": 0, "missing": 0},
      "recall_at_10": {"mean": 0.0, "n": 0, "missing": 0},
      "mrr_at_5": {"mean": 0.0, "n": 0, "missing": 0},
      "ndcg_at_5": {"mean": 0.0, "n": 0, "missing": 0}
    },
    "citation_and_answer_control": {
      "faithfulness": {"mean": 0.0, "n": 0, "missing": 0},
      "answer_relevancy": {"mean": 0.0, "n": 0, "missing": 0},
      "citation_accuracy": {"mean": 0.0, "n": 0, "missing": 0},
      "hallucination_flag": {"mean": 0.0, "n": 0, "missing": 0},
      "unanswerable_detection_flag": {"mean": 0.0, "n": 0, "missing": 0}
    }
  },
  "failure_type_counts": {
    "retrieval_failure.gold_evidence_not_in_top_k": 0
  },
  "latency_summary": {
    "scope": "private_runner_wall_clock",
    "total_wall_clock_ms": 0.0,
    "mean_wall_clock_ms_per_question": 0.0
  },
  "known_limitations": [
    "Private aggregate only; raw cases and traces remain local.",
    "Answer metrics are deterministic contract checks, not an LLM judge.",
    "No retrieval, reranking, prompt, chunking, or verifier optimization is included."
  ]
}
```

금지 필드:

- raw `question`, `answer`, `answer_text`, `claims`, `citations`
- `gold_evidence`, `retrieved_chunks`, `text`, `text_preview`
- customer/project names, private document filenames, exact private paths
- `doc_id`, `chunk_id`처럼 private corpus를 역추적할 수 있는 per-case identifier
