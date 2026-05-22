# Trajectory rationality (ADR 0056)

- n: 221 (skipped_no_trace=0; cases_with_synthesis_llm_call=166)
- backend: stub
- model: stub

## Per-axis mean + 95 % CI

| axis | mean | 95 % CI | effective_n |
|---|---:|---|---:|
| `planner_decomposition` | 0.497 | (0.462, 0.535) | 221 |
| `retrieval_recalls` | 0.511 | (0.475, 0.548) | 221 |
| `answer_reasoning` | 0.498 | (0.451, 0.539) | 166 |

## Bottom 3 cases per axis (rationale review)

> case ids omitted — full per-case ids live in the gitignored `rationality.local.json` (ADR 0005/0056 aggregate-only zone).

### `planner_decomposition` — bottom 3

- #1 (slice=single_doc) = 0.001 — stub: SHA-256(trace subset, axis, case_id)
- #2 (slice=single_doc) = 0.005 — stub: SHA-256(trace subset, axis, case_id)
- #3 (slice=abstention) = 0.010 — stub: SHA-256(trace subset, axis, case_id)

### `retrieval_recalls` — bottom 3

- #1 (slice=abstention) = 0.000 — stub: SHA-256(trace subset, axis, case_id)
- #2 (slice=single_doc) = 0.004 — stub: SHA-256(trace subset, axis, case_id)
- #3 (slice=single_doc) = 0.010 — stub: SHA-256(trace subset, axis, case_id)

### `answer_reasoning` — bottom 3

- #1 (slice=abstention) = 0.006 — stub: SHA-256(trace subset, axis, case_id)
- #2 (slice=single_doc) = 0.007 — stub: SHA-256(trace subset, axis, case_id)
- #3 (slice=single_doc) = 0.008 — stub: SHA-256(trace subset, axis, case_id)
