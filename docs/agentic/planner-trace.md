# Planner & Query-Rewrite Trace Schema (v1)

This document is the reviewer-facing reference for the local trace artifacts produced by `run_rag_query` and persisted under `reports/traces/<run>/<case_id>.trace.json` by `eval/run_eval.py`.

The goal is that a reviewer can open one `.trace.json` file and reconstruct *what the planner decided, why it rewrote (or didn't rewrite) the query, and where time was spent* — without having to re-run the pipeline.

Builders live in [rag_core.py](../rag_core.py): `build_query_rewrite_trace`, `build_planner_trace`, `build_result_trace`.

## Top-level shape

```jsonc
{
  "schema_version": 1,
  "query_rewrite": { ... },
  "planner":       { ... },
  "answer_schema": { ... }
}
```

`schema_version` is currently `1`. Field additions that are backward-compatible (new optional keys) do not bump this; a breaking shape change will (paired with `#63` answer-schema v2).

## `query_rewrite`

Captures conversational context resolution and any prefix injection done before retrieval.

| Field | Type | Notes |
|---|---|---|
| `original_query` | str | Verbatim user query for this turn. |
| `resolved_query` | str | Query actually sent to retrieval. Equals `original_query` when no rewrite occurred. |
| `rewritten` | bool | True iff `resolved_query != original_query`. |
| `rewrite_type` | str | One of `conversation_state_prefix`, `explicit_context`, `clarification_required`, `none`. |
| `context_source` | str | Origin of resolution signal: `conversation_state`, `context_entities`, `query`, or `none`. |
| `context_status` | str | `resolved`, `needs_clarification`, `not_needed`, etc. |
| `context_resolution_confidence` | float (0.0–1.0) | Confidence of the resolution decision. Below `CONTEXT_RESOLUTION_THRESHOLD` triggers clarification. |
| `reason` | str | Diagnostic tag (e.g. `weak_active_state`, `ambiguous_active_state`, `no_active_state`). |
| `context_entities` | list[str] | Carried-over agency / entity names. |
| `context_projects` | list[str] | Carried-over project names. |
| `active_doc_ids` | list[str] | Doc IDs in the active conversation state. |
| `readable_summary` | str | Single-line human description of the rewrite outcome. |

### Reading tips

- A follow-up that abstained with `rewrite_type=clarification_required` and low `context_resolution_confidence` is the textbook "we couldn't pin down the referent" path.
- `rewrite_type=conversation_state_prefix` + non-empty `context_entities` means a prior turn's agency/project was prepended to the query.

## `planner`

Captures the retrieval/answer plan and per-stage attempts.

| Field | Type | Notes |
|---|---|---|
| `query_type` | str | `single_doc`, `comparison`, `follow_up`, `abstention`. |
| `pipeline` | str | Active pipeline name (e.g. `agentic_full`, `naive`). |
| `prompt_profile` | str | Prompt profile selected for this run. |
| `strategy` | str | High-level retrieval strategy label. |
| `retrieval_mode` | str | `flat` or hierarchical mode. |
| `metadata_first` | bool | Whether the metadata-first path was taken. |
| `rerank` | bool | Reranker enabled. |
| `verifier_retry` | bool | Verifier-driven retry enabled. |
| `stage_sequence` | list[str] | Filter stages attempted in order (e.g. `["strict", "reduced", "relaxed"]`). |
| `selected_stage` | str | Final filter stage that produced the answer. |
| `selected_top_k` | int \| null | Final top-k used. |
| `retrieval_budget` | object | Top-k planning details (defaults, query-type override, reason). |
| `metadata_candidate_count` | int \| null | Candidate doc count from metadata resolution. |
| `metadata_selected_doc_ids` | list[str] | Doc IDs selected by metadata-first resolution. |
| `metadata_ambiguous` | bool | Metadata resolution flagged ambiguity. |
| `comparison_coverage` | object \| null | Comparison coverage diagnostics (when applicable). |
| `stage_latencies_ms` | object | `{query_analysis_ms, context_resolution_ms, answer_generation_ms}`. |
| `attempts` | list[object] | Per-stage attempt records: `stage`, `top_k`, `verified`, `verification_reasons`, `metadata_doc_ids`. |
| `readable_summary` | str | Single-line plan summary, e.g. `single_doc planned with agentic_full stage=strict top_k=4 metadata_docs=['rfp-agency-a-ai-quality']`. |

### Reading tips

- Walk `attempts` in order to see retry chain. The first `verified=true` is what fed answer generation.
- Stage-level `retrieve_ms` / `verify_ms` live inside each attempt entry; the top-level `stage_latencies_ms` covers analysis / context resolution / answer generation.
- Pair `metadata_selected_doc_ids` with `query_rewrite.active_doc_ids` to see whether the planner respected the active conversation context.

## `answer_schema`

Mirrors the answer envelope (`schema_version`, `status`, `status_reason`, `query_type`, `claim_count`) so a reviewer can decide whether the verifier abstained without opening the answer file.

## Privacy & redaction

Traces contain document IDs, agency names, and project names from the indexed corpus. They are written to **local files only** (`reports/traces/...`) and are not uploaded by any code path in this repo.

For reviewer hand-off where document IDs / entities are sensitive:

```bash
# mask both doc IDs and entities
python eval/run_eval.py --config eval/dev_config.yaml --redact_trace all

# mask only doc IDs
python eval/run_eval.py --config eval/dev_config.yaml --redact_trace doc_ids
```

Redaction replaces each list entry with the literal `"<redacted>"` while preserving list length, so structural shape (e.g. "two doc IDs were selected") is still inspectable. `planner.readable_summary` is rewritten in lockstep so it cannot leak the selected doc IDs via its summary string. The in-memory result returned by `run_rag_query` is never mutated — redaction applies only at the trace-write boundary.

The `eval_summary.json` records the effective redaction state under `trace_redaction`.

## Regression coverage

`tests/test_fuzzy_retrieval.py` enforces:

- Schema version 1.
- Required field sets on `query_rewrite` and `planner` (so a future PR cannot silently drop a field).
- `stage_latencies_ms` keys present and numeric.
- `redact_trace` masks list fields without mutating the input or losing length.
