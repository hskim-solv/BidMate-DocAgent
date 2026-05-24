# Private Real-Eval Manifest Schema

이 manifest는 private real-eval의 문서 inventory 단일 출처(source of truth)다.
원문 파일명이나 고객명은 커밋하지 않는다. 아래 값은 모두 fake placeholder다.

## Required Columns

| column | purpose |
|---|---|
| `doc_id` | Stable anonymized document id. Example: `doc_001`. |
| `file_path` | Local private file path, usually under ignored `data/files_kordoc/`. |
| `document_type` | File family such as `pdf`, `hwp`, or `hwpx`. |
| `split` | Eval split, for example `private_real_eval`. |

## Recommended Columns

| column | purpose |
|---|---|
| `page_count` | Page count when available. |
| `source_category` | Coarse non-sensitive source bucket. |
| `privacy_redaction` | Local handling marker such as `raw_private`. |
| `source_digest` | Optional local digest for stale-file detection. |

## Example

```csv
doc_id,file_path,document_type,split,page_count,source_category,privacy_redaction,source_digest
doc_001,data/files_kordoc/doc_001.pdf,pdf,private_real_eval,12,rfp,raw_private,sha256-placeholder
doc_002,data/files_kordoc/doc_002.hwp,hwp,private_real_eval,8,rfp,raw_private,sha256-placeholder
```

`support_text`, raw document text, real filenames, customer names, and absolute
local paths must stay out of committed docs and summaries.

