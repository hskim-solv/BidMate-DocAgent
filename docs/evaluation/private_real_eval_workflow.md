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

Canonical local layout:

```text
eval/real_config.local.yaml
data/data_list.csv
data/files/
data/index/real100/
data/index/real100/hwp_pdf_artifacts/
reports/real100/
```

Use `eval/real_config.local.yaml` for the readiness audit, validate-only step,
and local private baseline run. Do not create a second local config just to run
the pre-improvement readiness workflow.

## Local Inventory And Canonical Mapping

As of 2026-05-24, the maintainer local working copy has enough private corpus
cache to prepare the Naive RAG baseline runner, but not in the preferred
`data/private/` layout:

| Candidate category | Observed local state | Canonical target | Action |
|---|---:|---|---|
| Source documents | 100 files | `data/files/` | Keep local-only; never commit. |
| HWP citation PDFs | generated on rebuild | `data/index/real100/hwp_pdf_artifacts/` | Preserve local-only; citations refer to these LibreOffice converted PDFs. |
| Manifest | 100 rows | `data/data_list.csv` | Keep local-only; never commit. |
| Existing index | 100 documents / 26,376 chunks | `data/index/real100/` | Use only if it matches the manifest and corpus; otherwise rebuild. |
| Gold labels/questions | `cases:` in local config | `eval/real_config.local.yaml` | Curate local-only cases; add explicit `gold_evidence` or `gold_chunk_ids` when needed. |
| Redacted summary | Local reports | `reports/real100/` aggregate files | Generate only after a successful private run and redaction checks. |

If an external private root is used, point `REAL_EVAL_ROOT` or the nested
`real_eval:` paths in `eval/real_config.local.yaml` at that root. Do not write
machine-specific absolute paths into committed files.

The readiness audit can derive chunk-level gold from `expected_doc_ids` +
`expected_terms` when the index contains matching chunks. For performance
claims, manually review the resolved evidence and prefer explicit local-only
`gold_evidence` or `gold_chunk_ids` on answerable cases.

## Local Config

```bash
cp eval/real_config.template.yaml eval/real_config.local.yaml
```

Fill only local paths and local measurement settings. Do not put
machine-specific absolute paths, private filenames, raw questions, raw answers,
or private document text in committed files.

## Gold Evidence Schema

`eval/real_config.local.yaml` owns private questions and gold labels. Each
answerable case should have either explicit `gold_evidence[].chunk_id`,
`gold_chunk_ids`, or enough `expected_doc_ids` + `expected_terms` for the audit
to resolve matching chunks from the local index. Unanswerable rows use no gold
evidence.

```yaml
cases:
  - id: case-001
    query: "...local private question..."
    answerable: true
    expected_doc_ids: ["...local doc id..."]
    expected_terms: ["...local expected term..."]
    gold_evidence:
      - doc_id: "...local doc id..."
        chunk_id: "...local chunk id..."
  - id: case-002
    query: "...local private unanswerable question..."
    answerable: false
    expected_doc_ids: []
    expected_terms: []
```

Raw questions and local identifiers can be sensitive, so this file is
local-only and gitignored.

## Gitignore Safety

The workflow expects these private paths to remain ignored:

- `eval/real_config.local.yaml`
- `configs/eval/private_real_eval.local.yaml` (compatibility path only)
- `configs/eval/*.local.yaml`
- `data/private/`
- `data/files/`
- `data/data_list.csv`
- `data/index/private*/`
- `data/index/real*/`
- `data/index/real100/`
- `data/index-private-hardcase/`
- `experiments/private_runs/`
- `reports/real*/`
- `reports/real100/eval_summary.json`
- `reports/real100/raw/`
- `reports/private_real_eval_summary.raw.json`

The readiness tools validate that private inputs and output paths are
gitignored or outside the repo before they process local data.

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
`index.json` is present. Do not infer the embedding model from
`DEFAULT_EMBEDDING_MODEL` alone: the build surface is determined by both
`--embedding_backend` and `--model`.

The readiness scaffold also prints the expected build command shape when local
private documents and manifest are present:

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --output_dir data/index/real100 \
  --hwp_loader pdf_pymupdf4llm \
  --pdf_loader pdf_pymupdf4llm \
  --embedding_backend hashing
```

That command is the deterministic offline hashing surface. It records
`embedding.backend=hashing` and `embedding.model=local-hashing-bow`; it is not a
MiniLM semantic run even though the CLI default model constant is MiniLM.

Use separate named targets for semantic private runs:

```bash
make real-eval-minilm    # MiniLM sentence-transformers baseline
make real-eval-semantic  # BGE-M3 semantic comparison
```

These write to separate local index/output/report directories and do not update
the canonical hashing `real100` path.

## Validate Private Naive RAG Inputs

```bash
python3 scripts/check_private_real_eval_readiness.py --config eval/real_config.local.yaml
```

Validation is fail-closed for missing documents, missing metadata, missing gold
evidence, missing answerable/unanswerable split, invalid answerable/unanswerable
evidence shape, and private paths that are not gitignored or outside the repo.

On failure, the validator reports only field names, categories, and
counts, for example `missing_required_input: gold_evidence_path` or
`missing_explicit_gold_chunk_id: answerable_questions count=N`. It must not
print raw questions, raw answers, support text, document names, `doc_id`,
`chunk_id`, or exact local paths.

## Run Private Naive RAG Eval

Run the local private baseline from the same config:

```bash
python3 scripts/run_private_real_eval.py --config eval/real_config.local.yaml
```

Or use the Make target:

```bash
make real-eval
```

`make real-eval` is the hashing/offline workflow-validation run. Do not use it
as a dense semantic retrieval baseline or performance claim. Use
`make real-eval-minilm` for the named MiniLM baseline, and `make
real-eval-semantic` for the BGE-M3 comparison surface.

To write the committable aggregate candidate after review:

```bash
make real-eval-baseline-update
```

Generated raw artifacts stay under ignored local report/output paths. Depending
on the runner, artifacts include:

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
