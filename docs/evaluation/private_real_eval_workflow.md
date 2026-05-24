# Private Real-Eval Workflow

Smoke eval is CI/regression only.
Synthetic benchmark is public reproducibility and ablation only.
Private real-eval is required for credible real-world baseline claims.

이 workflow는 private data 없이 repository를 준비하는 scaffold다. 현재 이 문서는
Naive RAG 기준선(baseline)을 측정했다는 증거가 아니며, private raw content는
커밋하지 않는다.

## Why This Exists

Public smoke(smoke)와 synthetic benchmark(합성 벤치마크)는 재현성(reproducibility)과
회귀(regression) 확인에 충분하지만, 실제 RFP 문서에서 baseline claim을 하려면
private real-eval이 필요하다. 단, private real-eval은 문서·질문·근거(evidence)가
민감하므로 raw output은 local-only로 두고 redacted aggregate만 검토 후 커밋한다.

Required wording:

- Smoke eval is CI/regression only.
- Synthetic benchmark is public reproducibility and ablation only.
- Private real-eval is required for credible real-world baseline claims.
- No private raw content should be committed.
- Redacted aggregate summaries may be committed only if they pass privacy checks.

## Local File Layout

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

All raw private inputs and run artifacts above are ignored except the redacted
summary output path, which is allowlisted only for aggregate-only summaries that
pass privacy checks.

## Config

Create the local config from the committed template:

```bash
cp eval/real_config.template.yaml eval/real_config.local.yaml
```

Then edit local paths manually. Do not put machine-specific absolute paths in
the committed template. `eval/real_config.local.yaml` is gitignored.

## Gitignore Safety

The scaffold expects these private paths to remain ignored:

- `eval/real_config.local.yaml`
- `configs/eval/*.local.yaml`
- `data/files/`
- `data/files_kordoc/`
- `data/private/`
- `data/data_list.csv`
- `data/index/real100/`
- `data/index/real100_kordoc/`
- `data/index-private-hardcase/`
- `experiments/private_runs/`
- `reports/real100/eval_summary.json`
- `reports/real100/raw/`
- `reports/private_real_eval_summary.raw.json`

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

## Index Build Expectation

When documents and manifest are present, build the local private index under an
ignored directory. The readiness validator prints the command shape:

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files_kordoc \
  --output_dir data/index/real100_kordoc \
  --hwp_loader kordoc \
  --pdf_loader kordoc \
  --embedding_backend hashing
```

This is infrastructure readiness only. It does not tune retrieval(retrieval),
reranking(reranking), prompts, chunking, verifier, or self-correction.

## Run Private Naive RAG Eval

```bash
python3 scripts/run_private_real_eval.py --config eval/real_config.local.yaml
```

The wrapper calls the readiness validator first. If files are missing, it fails
without writing private raw output. If runnable, it delegates to the existing
Naive RAG contract and writes raw artifacts only under ignored
`experiments/private_runs/`.

## Export Redacted Summary

```bash
python3 scripts/export_private_real_eval_summary.py \
  --run-dir experiments/private_runs/<run_id> \
  --out reports/private_real_eval_summary.redacted.json
```

The redacted summary may include aggregate document count, chunk count, question
count, retrieval metrics, citation metrics, answer/control metrics, latency
metrics, failure type counts, and known limitations.

The redacted summary must not include raw document text, raw questions, raw
generated answers, `support_text`, customer names, private filenames, absolute
local paths, or sensitive private file ids.

## What Can Be Committed

- `eval/real_config.template.yaml`
- readiness/run/export scripts
- schema docs and workflow docs
- tests and governance checks
- `reports/private_real_eval_summary.redacted.json` only after exporter and
  governance privacy checks pass

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

Current repository status remains **A. Not ready** until local private files are
provided. No Naive RAG real baseline has been measured yet.

## Next Manual Steps

1. Copy the template to `eval/real_config.local.yaml`.
2. Place private documents, manifest, questions, and gold evidence in ignored
   local paths.
3. Run the readiness validator.
4. Build the private index if the validator reports only index blockers.
5. Run the private Naive RAG wrapper.
6. Export the redacted summary.
7. Run governance and tests before committing any redacted aggregate.

