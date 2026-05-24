# Private Real-Eval Workflow

Smoke eval is CI/regression only.
Synthetic benchmark is public reproducibility and ablation only.
Private real-eval is required for credible real-world baseline claims.
No private raw content should be committed.
Redacted aggregate summaries may be committed only if they pass privacy checks.

This workflow prepares and runs a local-only private real-eval path for the
Naive RAG baseline. It is not itself proof that a private baseline has been
measured; private documents, raw questions, raw answers, raw evidence, and raw
run outputs must stay local. Only redacted aggregate summaries may be reviewed
for commit.

## Why This Exists

Public smoke(smoke) and synthetic benchmark(합성 벤치마크) surfaces are useful
for reproducibility(reproducibility), ablation(절제), and regression(회귀)
checks, but they are not sufficient for real RFP baseline claims. Private
real-eval is the credible measurement path because it uses local private
documents and explicit gold evidence(근거).

This workflow measures the existing Naive RAG baseline only. It does not
improve retrieval(검색), reranking(재순위), prompts(프롬프트), chunking(청킹),
verification(검증), or self-correction(자가수정).

## Evaluation Surfaces

| Surface | Data | Purpose | Valid for performance claims |
|---|---|---|---|
| Smoke eval | committed fixture | CI/regression sanity | No |
| Synthetic benchmark | committed/generated public data | reproducible framework validation | Provisional only |
| Private real-eval | local private documents | credible baseline measurement | Yes, aggregate-only |

## Supported Local Layouts

Preferred Naive RAG contract layout:

```text
configs/eval/private_real_eval.local.yaml
data/private/files/
data/private/data_list.csv
data/private/gold_evidence.jsonl
data/private/index/
experiments/private_runs/
```

Readiness scaffold / older real-eval convention:

```text
eval/real_config.local.yaml
data/data_list.csv
data/files_kordoc/
data/private/questions.jsonl
data/private/gold_evidence.jsonl
data/index/real100_kordoc/
experiments/private_runs/
reports/private_real_eval_summary.redacted.json
```

Use `configs/eval/private_real_eval.local.yaml` when the goal is the Naive RAG
baseline contract runner. Use `eval/real_config.local.yaml` and the readiness
scripts when checking whether the local private corpus is prepared.

## Local Inventory And Canonical Mapping

As of 2026-05-24, the maintainer local working copy has enough private corpus
cache to prepare the Naive RAG baseline runner, but not in the preferred
`data/private/` layout:

| Candidate category | Observed local state | Canonical target | Action |
|---|---:|---|---|
| Source documents | 100 files | `data/private/files/` | Symlink or copy locally; never commit. |
| Kordoc cache | 101 files | `data/private/files_kordoc/` | Symlink as the sibling cache for `data/private/files/`. |
| Manifest | 100 rows | `data/private/data_list.csv` | Symlink or copy locally; never commit. |
| Existing index | 100 documents / 26,376 chunks | `data/private/index/` | Symlink only if it matches the manifest and corpus; otherwise rebuild. |
| Gold labels/questions | No canonical file found | `data/private/gold_evidence.jsonl` | Regenerate or curate local-only labels with raw questions and explicit `gold_evidence[].chunk_id`. |
| Redacted summary | Not present | `reports/private_real_eval_summary.redacted.json` | Generate only after a successful private run and redaction checks. |

Use a local shell variable for the private cache root. Do not write its value
into committed files:

```bash
PRIVATE_CACHE_ROOT=/path/to/local/main/worktree
mkdir -p data/private
ln -s "$PRIVATE_CACHE_ROOT/data/files" data/private/files
ln -s "$PRIVATE_CACHE_ROOT/data/files_kordoc" data/private/files_kordoc
ln -s "$PRIVATE_CACHE_ROOT/data/data_list.csv" data/private/data_list.csv
ln -s "$PRIVATE_CACHE_ROOT/data/index/real100" data/private/index
```

If labels are converted from an older `eval/real_config.local.yaml`, write the
result only to `data/private/gold_evidence.jsonl`. The converted file is
runnable only after every answerable row has explicit chunk-level gold evidence
and every unanswerable row has an empty `gold_evidence` list. Any answerable
row that cannot be resolved to a chunk should be omitted from a temporary
runnable subset or manually labeled before using the result for performance
claims.

## Local Config

For readiness checks:

```bash
cp eval/real_config.template.yaml eval/real_config.local.yaml
```

For the Naive RAG contract runner:

```bash
cp configs/eval/private_real_eval.template.yaml configs/eval/private_real_eval.local.yaml
```

Fill only local paths and local measurement settings. Do not put
machine-specific absolute paths, private filenames, raw questions, raw answers,
or private document text in committed files.

## Gold Evidence Schema

`gold_evidence_path` is JSONL. Each answerable row needs explicit
`gold_evidence[].chunk_id`; unanswerable rows use an empty `gold_evidence` list.

```json
{"question_id":"case-001","question":"...local private question...","answerable":true,"expected_terms":["..."],"gold_evidence":[{"doc_id":"...","chunk_id":"..."}]}
{"question_id":"case-002","question":"...local private unanswerable question...","answerable":false,"gold_evidence":[]}
```

Raw questions can be sensitive, so this file is local-only and gitignored.

## Gitignore Safety

The workflow expects these private paths to remain ignored:

- `configs/eval/private_real_eval.local.yaml`
- `eval/real_config.local.yaml`
- `configs/eval/*.local.yaml`
- `data/private/`
- `data/files/`
- `data/files_kordoc/`
- `data/data_list.csv`
- `data/index/private*/`
- `data/index/real*/`
- `data/index/real100/`
- `data/index/real100_kordoc/`
- `data/index-private-hardcase/`
- `experiments/private_runs/`
- `reports/real*/`
- `reports/real100/eval_summary.json`
- `reports/real100/raw/`
- `reports/private_real_eval_summary.raw.json`

The private runner validates that `documents_dir`, `data_list_path`,
`questions_path`, `gold_evidence_path`, `index_dir`, and `output_dir` are
gitignored or outside the repo before it processes local data.

## Validate Readiness

```bash
python3 scripts/check_private_real_eval_readiness.py --config eval/real_config.local.yaml
```

The validator prints a readiness verdict:

- `A. Not ready`
- `B. Config ready, data missing`
- `C. Data present, labels/index missing`
- `D. First baseline runnable`
- `E. Portfolio-level readiness possible after manual review`

The validator reports counts and blockers only. It does not print private
filenames, raw questions, raw answers, support text, document text, customer
names, or absolute local paths.

## Build Or Load The Private Index

The contract runner builds the index when `index_build.mode: build_if_missing`
and `<index_dir>/index.json` is absent. It loads the existing index when
`index.json` is present. The template uses the project MiniLM default so the
private run measures dense semantic retrieval, not the hashing smoke fallback.

The readiness scaffold also prints the expected build command shape when local
private documents and manifest are present:

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files_kordoc \
  --output_dir data/index/real100_kordoc \
  --hwp_loader kordoc \
  --pdf_loader kordoc \
  --embedding_backend hashing
```

## Validate Private Naive RAG Inputs

```bash
python3 -m eval.naive_rag.private_real_eval \
  --config configs/eval/private_real_eval.local.yaml \
  --validate-only
```

Validation is fail-closed for missing documents, missing metadata, missing gold
evidence, missing answerable/unanswerable split, missing explicit
`gold_evidence[].chunk_id` on answerable rows, non-empty gold evidence on
unanswerable rows, and private paths that are not gitignored or outside the
repo.

On failure, the private runner reports only field names, categories, and
counts, for example `missing_required_input: gold_evidence_path` or
`missing_explicit_gold_chunk_id: answerable_questions count=N`. It must not
print raw questions, raw answers, support text, document names, `doc_id`,
`chunk_id`, or exact local paths.

## Run Private Naive RAG Eval

Preferred contract runner:

```bash
python3 -m eval.naive_rag.private_real_eval \
  --config configs/eval/private_real_eval.local.yaml
```

To also write the committable aggregate candidate:

```bash
python3 -m eval.naive_rag.private_real_eval \
  --config configs/eval/private_real_eval.local.yaml \
  --redacted-summary-path reports/private_real_eval_summary.redacted.json
```

Readiness scaffold wrapper:

```bash
python3 scripts/run_private_real_eval.py --config eval/real_config.local.yaml
```

Generated raw artifacts stay under ignored `experiments/private_runs/<run_id>/`.
The contract runner writes:

```text
experiments/private_runs/<run_id>/
metrics.json
retrieved_chunks.jsonl
answers.jsonl
failure_cases.jsonl
summary.md
redacted_summary.json
```

## Metrics

Trustworthy within this workflow:

- retrieval metrics: `recall_at_5`, `recall_at_10`, `mrr_at_5`, `ndcg_at_5`
- citation/control metrics: `citation_accuracy`, `faithfulness`,
  `answer_relevancy`, `hallucination_flag`, `unanswerable_detection_flag`
- aggregate failure type counts
- dataset cardinalities and index chunk counts

Still provisional:

- answer quality as judged by deterministic term checks
- wall-clock latency unless the same hardware/process warmup is used
- any comparison against non-naive systems unless the same private set and
  index provenance are held fixed

## Redacted Summary

The contract runner writes:

```text
experiments/private_runs/<run_id>/redacted_summary.json
```

The readiness scaffold exporter writes:

```bash
python3 scripts/export_private_real_eval_summary.py \
  --run-dir experiments/private_runs/<run_id> \
  --out reports/private_real_eval_summary.redacted.json
```

Redacted summaries may include aggregate document count, chunk count, question
count, retrieval metrics, citation metrics, answer/control metrics, latency
metrics, failure type counts, and known limitations.

They must not include raw document text, raw questions, raw generated answers,
`support_text`, customer names, private filenames, absolute local paths,
`doc_id`, `chunk_id`, or sensitive private file ids.

## What Can Be Committed

- config templates
- readiness/run/export scripts
- schema docs and workflow docs
- tests and governance checks
- redacted aggregate reports only after exporter and privacy checks pass

## What Must Never Be Committed

- real private documents
- private raw questions
- private gold evidence
- private raw outputs
- `support_text`
- customer names
- private filenames
- absolute local paths
- raw generated answers

## Current Readiness Status

Current repository status remains **A. Not ready** until local private files and
explicit gold evidence are provided. No Naive RAG real baseline has been
measured by this repository state.

No Naive RAG real baseline has been measured yet.

## Next Manual Steps

1. Copy the relevant template to a local ignored config.
2. Place private documents, manifest, questions, and gold evidence in ignored
   local paths.
3. Run readiness validation or the contract runner with `--validate-only`.
4. Build the private index if validation reports only index blockers.
5. Run the private Naive RAG baseline.
6. Export or inspect only redacted aggregate summaries.
7. Run governance and tests before committing any redacted aggregate.

## Non-Goals

This workflow intentionally does not add hybrid search, reranking, query
expansion, prompt tuning, chunking changes, citation verifier optimization,
self-correction, or any other RAG performance improvement. It only creates a
safe local-only path to measure the Naive RAG baseline on private real
documents.
