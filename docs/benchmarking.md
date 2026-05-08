# Benchmarking

이 저장소의 benchmark 관리는 커밋 가능한 정의와 로컬 실행 산출물을 분리한다. 목적은 포트폴리오 리뷰어가 실험 설계와 비교 결과를 빠르게 이해하되, raw prediction이나 비공개 원본 RFP가 Git에 섞이지 않게 하는 것이다.

## Source Of Truth

- `benchmarks/suites/public_synthetic_rfp.yaml`: 공개 synthetic RFP benchmark suite 정의
- `benchmarks/suites/private_hardcase_rfp.example.yaml`: 비공개 hard-case benchmark용 local-only suite template
- `benchmarks/ablations/rag_quality_axes.yaml`: `naive_baseline` control, primary run, ablation flag 정의
- `benchmarks/registry.schema.json`: registry와 run manifest의 최소 schema
- `benchmarks/registry.json`: 커밋 가능한 집계 registry

`benchmarks/`에는 실행 정의와 집계 지표만 둔다. 원문 RFP, raw logs, per-example dump는 커밋하지 않는다. 기본 baseline은 fixed-size chunking과 dense top-k retrieval만 사용하는 `naive_baseline`이며, `full`은 metadata-first/rerank/verifier retry를 켠 비교 대상이다.

## Local Artifacts

`scripts/run_benchmark.py`는 실행별 산출물을 `artifacts/benchmarks/<run_id>/`에 저장한다.

```bash
python3 scripts/run_benchmark.py \
  --suite benchmarks/suites/public_synthetic_rfp.yaml \
  --ablations benchmarks/ablations/rag_quality_axes.yaml
```

생성되는 로컬 파일은 다음과 같다.

- `run_manifest.json`: run id, git commit, suite id, ablation flags, model/retriever/reranker/verifier config, metrics, latency, artifact path
- `eval_summary.json`: benchmark run의 aggregate eval summary
- `predictions.jsonl`: per-example prediction dump
- `latency_samples.jsonl`: per-example latency/retry sample
- `error_examples.jsonl`: metric이 실패하거나 partial로 판정된 비교용 error example
- `traces/`: per-example plan/diagnostics/evidence reference
- `logs/`: index build 등 command log

`artifacts/benchmarks/`는 `.gitignore` 대상이다. 공개 synthetic 실행이라도 raw prediction과 trace는 noisy하고 커밋 diff를 크게 만들기 때문에 로컬 검증용으로만 둔다.

## Summarization

로컬 manifest를 확인한 뒤 커밋 가능한 집계 registry와 사람이 읽는 요약 문서를 갱신한다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest artifacts/benchmarks/<run_id>/run_manifest.json
```

최신성 검증은 다음 명령을 사용한다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest artifacts/benchmarks/<run_id>/run_manifest.json \
  --check
```

요약 결과는 `benchmarks/registry.json`과 `docs/ablation-results.md`에 반영된다. 문서에는 2차 가공 결과와 집계 지표만 남기며, private RFP 기반 실험을 수행하더라도 원문이나 per-example output은 포함하지 않는다.

## Private Hard-case Slice

이슈 #24의 private hard-case slice는 공개 benchmark를 대체하지 않고 현실적인 문서 조건에서 품질 하락을 분리하기 위한 보조 suite다. `eval/private_hardcase.example.yaml`은 익명 case list와 `hardcase_categories` 형식을 보여준다. 실제 실행 파일은 `eval/private_hardcase.local.yaml`처럼 `.gitignore` 대상 local YAML로 복사해 사용한다.

`eval/run_eval.py`와 benchmark manifest는 `by_hardcase_category` 집계를 포함한다. 이 값만 registry/docs에 남기고 raw private prediction, trace, 원문 artifact는 `artifacts/benchmarks/` 아래 local-only 산출물로 유지한다. 운영 절차와 금지 항목은 [`docs/private-hardcase-benchmark.md`](private-hardcase-benchmark.md)에 정리했다.
