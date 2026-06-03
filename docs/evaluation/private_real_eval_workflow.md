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

Canonical local layout for current claim-bearing work:

```text
data/private/real100_v2/real_config_v2.local.yaml
data/data_list.csv
data/files/
data/index/real100_v2/
reports/real100_v2/
```

Use the `real100_v2` config and aggregate surface for all new private eval
tasks. Legacy real100/v1 paths, 221-case aggregates, and kordoc/v1 index
evidence are disabled until the maintainer explicitly re-enables them. Validate
the current surface with `make real-eval-v2-check`, `make real-eval-v2-inventory`,
and `make real-eval-v2-guard`.

### Current Path Guard

For new private Naive RAG eval work, the runner is fail-closed around the
current surface boundary:

- `output_dir`, `index_dir`, and `index_build.hwp_pdf_artifact_dir` must not
  target legacy `real100`, real100/v1, 221-case, or kordoc/v1 surfaces for new
  outputs.
- `run_id` must be a safe single path segment; do not use path separators or
  parent-directory traversal.
- `redacted_summary_path` may point at ignored local paths or committed
  redacted aggregate summaries such as `reports/*.redacted.json`, but never at
  raw private output paths.
- Raw private run artifacts stay local-only under ignored paths. Only redacted
  aggregate summaries may cross the commit boundary after privacy checks.

## Local Inventory And Canonical Mapping

As of 2026-05-24, the maintainer local working copy has enough private corpus
cache to prepare the Naive RAG baseline runner, but not in the preferred
`data/private/` layout:

| Candidate category | Observed local state | Canonical target | Action |
|---|---:|---|---|
| Source documents | 100 files | `data/files/` | Keep local-only; never commit. |
| HWP citation PDFs | generated on rebuild | `data/index/real100_v2/hwp_pdf_artifacts/` or another ignored v2-local artifact directory | Preserve local-only; legacy `data/index/real100/` artifact directories are archive-only for new writes. |
| Manifest | 100 rows | `data/data_list.csv` | Keep local-only; never commit. |
| Existing index | 100 documents / v2 chunks | `data/index/real100_v2/` | Use only if it matches the v2 manifest and corpus; otherwise rebuild outside tracked output. |
| Gold labels/questions | `cases:` in local config | `eval/real_config.local.yaml` | Curate local-only cases; add explicit `gold_evidence` or `gold_chunk_ids` when needed. |
| Redacted summary | Local reports | `reports/real100_v2/` aggregate files | Generate only after a successful private run and redaction checks. |

If an external private root is used, point `REAL_EVAL_ROOT` or the nested
`real_eval:` paths in `eval/real_config.local.yaml` at that root. Do not write
machine-specific absolute paths into committed files.

The readiness audit can derive chunk-level gold from `expected_doc_ids` +
`expected_terms` when the index contains matching chunks. For performance
claims, manually review the resolved evidence and prefer explicit local-only
`gold_evidence` or `gold_chunk_ids` on answerable cases.

## Local Config

For current `real100_v2` claim-bearing work, keep the ignored local config at
`data/private/real100_v2/real_config_v2.local.yaml` or set `REAL100_V2_CONFIG`
to another ignored local v2 config path.

Compatibility templates may still be copied for local-only experiments:

```bash
cp eval/real_config.template.yaml eval/real_config.local.yaml
```

Fill only local paths and local measurement settings, and keep every output path
inside an approved current surface such as `real100_v2`. Do not put
machine-specific absolute paths, private filenames, raw questions, raw answers,
or private document text in committed files.

## Gold Evidence Schema

The ignored local config owns private questions and gold labels. Each answerable
case should have either explicit `gold_evidence[].chunk_id`, `gold_chunk_ids`,
or enough `expected_doc_ids` + `expected_terms` for the audit to resolve
matching chunks from the local index. Unanswerable rows use no gold evidence.

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
  --output_dir data/index/real100_v2 \
  --hwp_loader pdf_pymupdf4llm \
  --pdf_loader pdf_pymupdf4llm \
  --embedding_backend hashing
```

That command shape is the deterministic offline hashing surface. It records
`embedding.backend=hashing` and `embedding.model=local-hashing-bow`; it is not a
MiniLM semantic run even though the CLI default model constant is MiniLM. For
new work, retarget any scaffolded or historical command examples to an approved
`real100_v2` local output directory before writing. Legacy real100/v1 semantic
Make targets are disabled until the maintainer explicitly re-enables them; use
the `real-eval-v2-*` targets for current inventory, guard, Chroma, and judge
runs.

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
python3 scripts/run_private_real_eval.py --config <ignored-local-config>
```

Or use the Make target:

```bash
make real-eval-v2-check
```

Current private real-eval workflow checks use the `real-eval-v2-*` targets.
Legacy `make real-eval`, `make real-eval-minilm`, and `make real-eval-semantic`
are fail-closed archive-only targets unless the maintainer explicitly
re-enables them; do not use their historical real100/v1 paths for new evidence
or claims. A direct runner invocation must also keep `output_dir`, `index_dir`,
`index_build.hwp_pdf_artifact_dir`, `run_id`, and `redacted_summary_path` inside
the current guard boundary.

The canonical `naive_baseline` vector-store backend is Chroma (ADR 0081).
`run_manifest.vector_store_backend` must be read alongside embedding
backend/model provenance before comparing aggregate runs. `memory` and `qdrant`
runs are backend controls, not replacement private baselines, unless produced
as separate paired same-config runs.

For a reproducible Chroma-backed private v2 eval run that does not overwrite the
committed baseline aggregate path:

```bash
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-chroma
```

By default this writes local output under `reports/real100_v2_chroma/`.

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
