# Trajectory rationality (ADR 0056)

- n: 221 (skipped_no_trace=0; cases_with_synthesis_llm_call=0)
- backend: stub
- model: stub

## Per-axis mean + 95 % CI

| axis | mean | 95 % CI | effective_n |
|---|---:|---|---:|
| `planner_decomposition` | 0.479 | (0.440, 0.517) | 221 |
| `retrieval_recalls` | 0.508 | (0.469, 0.544) | 221 |
| `answer_reasoning` | N/A | N/A | 0 |

## Bottom 3 cases per axis (rationale review)

### `planner_decomposition` — bottom 3

- `real_hanyeong_noanswer_트랙시스템_예산규모` (slice=abstention) = 0.001 — stub: SHA-256(trace subset, axis, case_id)
- `real_광주연구원_no_answer_penalty_rate` (slice=abstention) = 0.003 — stub: SHA-256(trace subset, axis, case_id)
- `real_BIFF_penalty_clause_no_answer` (slice=abstention) = 0.005 — stub: SHA-256(trace subset, axis, case_id)

### `retrieval_recalls` — bottom 3

- `real_gumi2025_response_time_concurrent_users_noanswer` (slice=abstention) = 0.000 — stub: SHA-256(trace subset, axis, case_id)
- `real_chosun_security_penalty_threshold` (slice=single_doc) = 0.004 — stub: SHA-256(trace subset, axis, case_id)
- `real_경기도일자리재단_worker_dispatch_legal_basis` (slice=abstention) = 0.013 — stub: SHA-256(trace subset, axis, case_id)

### `answer_reasoning` — no scored cases
