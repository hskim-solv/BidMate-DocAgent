# Private Real-Eval Gold Evidence Schema

Gold evidence lives in ignored local JSONL, normally
`data/private/gold_evidence.jsonl`. Every answerable question needs explicit
evidence. Evidence derived only from `expected_terms` is not acceptable for a
credible private retrieval(retrieval) baseline.

## Required Fields

| field | purpose |
|---|---|
| `evidence_id` | Stable anonymized id. Example: `ev_q001_001`. |
| `question_id` | Question id this evidence supports. Example: `q001`. |
| `doc_id` | Anonymized manifest doc id. Example: `doc_001`. |
| `chunk_id` | Stable chunk id from the private index. Example: `doc_001::chunk-003`. |

## Recommended Fields

| field | purpose |
|---|---|
| `page` or `page_span` | Page metadata for citation checks. |
| `support_text` | Local-only support snippet. The validator counts presence but never prints it. |
| `support_claim` | Local-only short claim label if needed. |

## Example

```jsonl
{"evidence_id":"ev_q001_001","question_id":"q001","doc_id":"doc_001","chunk_id":"doc_001::chunk-003","page_span":[4,4],"support_text":"PLACEHOLDER local-only support text"}
```

Committed summaries must not include `support_text`, raw document text, raw
questions, raw generated answers, private filenames, or absolute local paths.

