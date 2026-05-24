# Private Real-Eval Baseline Report Template

This template is for redacted aggregate reporting only. Do not include raw private questions, raw answers, document text, private filenames, customer names, exact local paths, `doc_id`, or `chunk_id`.

## Run Metadata

- Run ID: `TBD`
- System: Naive Dense RAG
- Data boundary: private local data, aggregate-only report
- Runner: `python3 -m eval.naive_rag.private_real_eval`
- Status: not executed until local validation passes

## Dataset Summary

| Metric | Value |
|---|---:|
| Documents | TBD |
| Chunks | TBD |
| Questions | TBD |
| Answerable questions | TBD |
| Unanswerable questions | TBD |

## Aggregate Metrics

| Metric | Mean | n | Missing |
|---|---:|---:|---:|
| Recall@5 | TBD | TBD | TBD |
| Recall@10 | TBD | TBD | TBD |
| MRR@5 | TBD | TBD | TBD |
| nDCG@5 | TBD | TBD | TBD |
| Citation accuracy | TBD | TBD | TBD |
| Faithfulness | TBD | TBD | TBD |
| Answer relevancy | TBD | TBD | TBD |
| Hallucination flag | TBD | TBD | TBD |
| Unanswerable detection flag | TBD | TBD | TBD |

## Latency Summary

| Metric | Value |
|---|---:|
| Scope | `private_runner_wall_clock` |
| Total wall-clock ms | TBD |
| Mean wall-clock ms per question | TBD |

## Failure Type Counts

| Failure type | Count |
|---|---:|
| TBD | TBD |

## Readiness Decision

Ready for improvement experiments only if all are true:

- At least 30 questions exist.
- Answerable and unanswerable split exists.
- Explicit gold evidence exists for answerable questions.
- Retrieval metrics are non-trivial and not saturated at 1.0.
- `failure_cases.jsonl` contains useful failure types.
- `redacted_summary.json` is generated.
- No private data, local config, or raw private output is committed.

## Known Limitations

- Private aggregate only; raw cases and traces remain local.
- Answer metrics are deterministic contract checks, not an LLM judge.
- Latency is runner wall-clock unless a narrower local profiler is added.
- No retrieval, reranking, prompt, chunking, verifier, or self-correction improvement is included.
