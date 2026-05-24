# Private Data Quality Audit

This workflow validates private corpus parsing and private real-eval labels
before any private baseline run. It is local-only. It does not change
retrieval, verifier, reranker, prompt, chunking, or answer behavior.

No public synthetic benchmark performance claim is produced by these audits.
Private real-eval remains local-only; only redacted aggregate summaries may be
reviewed as commit candidates.

## Required Order Before Baseline Measurement

1. Parse audit
2. Eval dataset audit
3. `private_real_eval` validate-only
4. `private_real_eval` run
5. Redacted summary review

## Privacy Boundary

The audit scripts may read private raw documents, raw questions, raw answers,
raw evidence content, local filenames, exact local locations, and raw index
identifiers. They must not write those values to their output artifacts.

Public-safe audit artifacts use aggregate counts and redacted hash references
only. They must not contain raw private keys such as `question`, `answer`,
`answer_text`, `gold_evidence`, `retrieved_chunks`, `text`, `text_preview`,
`doc_id`, `chunk_id`, `file_name`, or `path`.

Outputs must be written under ignored local directories such as
`experiments/private_runs/`, or outside the repository. The scripts refuse to
write into non-ignored repo paths.

## Parse Quality Audit

```bash
python3 scripts/audit_private_parse_quality.py \
  --documents-dir data/private/files \
  --data-list data/private/data_list.csv \
  --index-dir data/private/index \
  --out-dir experiments/private_runs/data_quality_audit
```

Outputs:

```text
experiments/private_runs/data_quality_audit/
parse_quality_summary.json
parse_quality_report.md
parse_quality_flags.jsonl
```

Checks:

- total document count
- parse success/failure count
- empty and very short document count
- chunk count
- chunk length min/p50/p95/max
- duplicate chunk ratio
- missing page metadata count/rate
- high garbled-character ratio count
- suspicious whitespace-only chunk count
- table-like chunk count
- date/amount/score-like token coverage count
- failed/suspicious document category counts

## Eval Dataset Audit

```bash
python3 scripts/audit_private_eval_dataset.py \
  --questions data/private/gold_evidence.jsonl \
  --gold-evidence data/private/gold_evidence.jsonl \
  --index-dir data/private/index \
  --out-dir experiments/private_runs/data_quality_audit
```

Outputs:

```text
experiments/private_runs/data_quality_audit/
eval_dataset_summary.json
eval_dataset_report.md
eval_dataset_flags.jsonl
```

Checks:

- question identifier uniqueness
- answerable/unanswerable count
- answerable rows have non-empty explicit evidence
- unanswerable rows have empty evidence
- every evidence document/chunk reference exists in the current index
- expected terms coverage in evidence content
- question type distribution when available
- duplicate and near-duplicate question detection
- overly copied question detection with redacted similarity scores only
- retrieval saturation warning when Recall@10 is already saturated
- minimum dataset size checks

## Interpreting Results

`passed: false` means at least one blocking error was found. Fix the private
local data or labels before running `private_real_eval`.

Warnings require review but do not by themselves prove the dataset is invalid.
Examples include small dataset size, near-duplicate questions, missing page
metadata, or retrieval saturation. Treat retrieval saturation as a dataset
measurement warning, not as a system performance claim.

## Follow-Up Validation

After both audits pass, run the private real-eval validator:

```bash
python3 -m eval.naive_rag.private_real_eval \
  --config configs/eval/private_real_eval.local.yaml \
  --validate-only
```

Then run the private baseline only after validate-only passes. Review only
redacted aggregate summaries before considering any commit.
