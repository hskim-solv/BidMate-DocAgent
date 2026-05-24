# Benchmarking

이 저장소의 평가(evaluation) 경계는 공개 fixture smoke와 private/internal eval을 분리한다. 목적은 리뷰어가 평가 프레임워크와 산출물 구조를 재현할 수 있게 하되, 공개 fixture를 성능 benchmark처럼 오해하지 않게 하는 것이다.

이 레포지토리는 공개 가능한 작은 fixture를 smoke test 용도로만 사용합니다. 실제 성능 평가는 레포지토리에 커밋하지 않는 private/internal eval set을 기준으로 수행하는 것을 전제로 합니다.

## Source Of Truth

- `eval/fixtures/smoke_rfp/raw/`: CI 재현성 확인용 공개 RFP fixture
- `eval/config.yaml`: fixture smoke eval config. 검색(retrieval), 답변 품질(answer quality), 인용 정확도(citation accuracy), 근거 검증(evidence verification), latency logging이 모두 실행되는지 확인한다.
- `harness/smoke.yaml`: harness 레벨 smoke profile
- `benchmarks/examples/private100_aggregate_manifest.example.json`: private aggregate-only summary flow 검증용 fixture
- `benchmarks/ablations/rag_quality_axes.yaml`: `naive_baseline` control, primary run, ablation flag 정의
- `benchmarks/registry.schema.json`: registry와 run manifest의 최소 schema
- `benchmarks/registry.json`: 커밋 가능한 aggregate registry. 공개 fixture smoke 결과를 성능 순위로 누적하지 않는다.

`benchmarks/`에는 실행 정의와 aggregate 지표만 둔다. 원문 RFP, raw logs, per-example dump, private case text는 커밋하지 않는다. 기본 baseline은 fixed-size chunking과 dense top-k retrieval만 사용하는 `naive_baseline`이며, `full`은 metadata-first/rerank/verifier retry를 켠 비교 대상이다.

## Public Fixture Smoke

공개 fixture smoke는 다음을 확인한다.

- `eval/run_eval.py`가 private data 없이 deterministic하게 실행된다.
- `reports/eval_summary.json`에 retrieval metrics, answer metrics, citation/evidence metrics, latency metrics가 남는다.
- `scripts/check_latency_slo.py`가 `eval/config.yaml`의 latency budget을 검증한다.
- PR CI가 네트워크 호출 없이 작은 corpus로 빠르게 회귀를 잡는다.

```bash
python3 scripts/build_index.py \
  --input_dir eval/fixtures/smoke_rfp/raw \
  --output_dir data/index \
  --embedding_backend hashing

python3 eval/run_eval.py \
  --config eval/config.yaml \
  --index_dir data/index \
  --output_dir reports

python3 scripts/check_latency_slo.py \
  --config eval/config.yaml \
  --summary reports/eval_summary.json
```

이 결과는 benchmark, aggregate report, portfolio headline metric의 source of truth가 아니다. 작은 fixture는 scoring/harness wiring과 재현성을 확인하는 smoke surface다.

## Private/Internal Eval

실제 성능 평가는 private/internal eval set에서 수행한다. 원문 문서, per-case prediction, trace는 local-only로 유지하고, 공개 가능한 범위에서는 aggregate-only artifact와 reviewer-friendly evidence 문서만 커밋한다.

private aggregate manifest는 같은 summary tooling을 사용하되, `suite.dataset`에는 `privacy`, `corpus_size`, `anonymized`, `comparison_group` 같은 commit-safe metadata만 둔다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest benchmarks/examples/private100_aggregate_manifest.example.json \
  --registry /private/tmp/private100-registry.json \
  --docs /private/tmp/private100-summary.md
```

이 예시는 흐름 검증용 fixture이며 실측 private 성과가 아니다. private 운영 원칙은 [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md)의 commit boundary 규칙을 따른다.

## Metrics

평가 지표는 하나의 종합 점수로 합치지 않고 다음 축으로 분리한다.

| Axis | Metrics | Primary Use |
|---|---|---|
| Retrieval quality | `chunk_recall@k`, MRR, nDCG, rerank delta | 검색(retrieval) 품질과 reranking 효과 |
| Answer quality | accuracy, groundedness, answer format compliance, abstention outcomes | 답변 품질(answer quality)과 보류(abstention) 정책 |
| Citation / evidence | citation precision, claim-citation alignment, evidence coverage | 인용 정확도(citation accuracy)와 근거(evidence) 검증 |
| Latency | p50/p95, stage latency, retry cost, cold-start samples | 운영 latency와 retry cost trade-off |

`eval_summary.json`에는 같은 metric block이 `by_query_type`, `by_hardcase_category`, `by_metadata_field`, `by_format`로 전파된다. 공개 fixture smoke는 이 schema가 유지되는지 확인하고, private/internal eval은 실제 delta와 aggregate evidence를 제공한다.

## Local Artifacts

`scripts/run_benchmark.py`는 실행별 산출물을 `artifacts/benchmarks/<run_id>/`에 저장한다.

- `run_manifest.json`: run id, git commit, suite id, ablation flags, model/retriever/reranker/verifier config, metrics, latency, artifact path
- `eval_summary.json`: run의 aggregate eval summary
- `predictions.jsonl`: per-example prediction dump
- `latency_samples.jsonl`: per-example latency/retry sample
- `error_examples.jsonl`: metric이 실패하거나 partial로 판정된 비교용 error example
- `traces/`: per-example plan/diagnostics/evidence reference
- `logs/`: index build 등 command log

`artifacts/benchmarks/`는 `.gitignore` 대상이다. 공개 fixture smoke 실행이라도 raw prediction과 trace는 noisy하고 커밋 diff를 크게 만들기 때문에 로컬 검증용으로만 둔다.

## Stage Latency & Retry Cost

이슈 #32 이후 eval은 단일 `latency_ms` 외에 stage 단위 latency를 함께 기록한다. 목표는 reviewer가 "응답 시간이 어느 단계에서 쌓이는지"와 "verifier retry가 품질 개선만큼 latency 비용을 정당화하는지"를 동시에 판단할 수 있게 하는 것이다.

`run_rag_query`의 diagnostics 필드:

- `stage_latency`: top-level stage별 ms — `query_analysis_ms`, `context_resolution_ms`, `answer_generation_ms`
- `filter_stage_attempts[i].retrieve_ms` / `verify_ms`: strict -> reduced -> relaxed 각 retry 시도의 retrieval+rerank, verifier 비용
- `cold_start`: 프로세스 첫 호출 여부. warm percentile에는 포함하지 않는다.

Reviewer가 latency trade-off를 읽을 때의 가이드:

1. `latency.p95`가 늘어났다면 먼저 `stage_latency.retrieve_ms`/`verify_ms`를 보고 어느 단계가 원인인지 식별한다.
2. `latency_by_retry_count["1+"]`의 p95와 `retry_cost.cases_with_retry`를 함께 보고, 같은 retry로 얻은 groundedness/citation/abstention gain이 latency 증가를 정당화하는지 판단한다.
3. `cold_start_samples`는 별도로 기록되므로 warm steady-state 비교를 흐리지 않는다.
