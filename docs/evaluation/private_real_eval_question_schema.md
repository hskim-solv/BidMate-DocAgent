# Private Real-Eval Question Schema

Private questions live in ignored local JSONL, normally
`data/private/questions.jsonl`. The readiness validator reports counts only and
does not print question text. Examples below are fake placeholders.

## Required Fields

| field | purpose |
|---|---|
| `question_id` | Stable anonymized id. Example: `q001`. |
| `question` | Private raw question text. Must remain local-only. |
| `answerable` | `true` when explicit gold evidence exists, `false` for abstention cases. |

## Recommended Fields

| field | purpose |
|---|---|
| `query_type` | Coarse type such as `single_doc`, `comparison`, `multi_hop`, or `abstention`. |
| `expected_doc_ids` | Optional anonymized expected doc ids for local review. |
| `category` | Coarse non-sensitive difficulty bucket. |

## Example

```jsonl
{"question_id":"q001","question":"PLACEHOLDER private question text","answerable":true,"query_type":"single_doc","expected_doc_ids":["doc_001"]}
{"question_id":"q002","question":"PLACEHOLDER unanswerable question text","answerable":false,"query_type":"abstention","expected_doc_ids":[]}
```

Do not commit raw questions, expected private answers, customer names, or
question text copied from real RFP documents.

