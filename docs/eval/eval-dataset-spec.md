# Eval Dataset Spec — Public Fixture Smoke / Private Internal Eval

이 문서는 공개 fixture smoke eval과 private/internal eval set의 경계를 설명한다. 공개 fixture는 benchmark가 아니라 평가 프레임워크가 재현 가능하게 동작하는지 확인하는 작은 smoke surface다.

이 레포지토리는 공개 가능한 작은 fixture를 smoke test 용도로만 사용합니다. 실제 성능 평가는 레포지토리에 커밋하지 않는 private/internal eval set을 기준으로 수행하는 것을 전제로 합니다.

- **평가셋 분리 정책**: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- **비공개 aggregate 정책**: [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md)

## 1. Public Fixture Corpus

공개 fixture는 `eval/fixtures/smoke_rfp/raw/`에 있는 5개 이하의 작은 RFP JSON 문서다. 목적은 CI에서 private data 없이 다음 계약을 확인하는 것이다.

| Fixture Role | Purpose |
|---|---|
| 기관 A/B 비교 문서 | comparison-aware balanced top-k, citation coverage 확인 |
| 기관 D chunk-boundary probe | chunk boundary와 parent reassembly 회귀 확인 |
| 기관 E main/supplement | single-turn ambiguity와 follow-up context 확인 |
| abstention case | 근거 부족 시 `insufficient` 응답 확인 |

이 corpus는 실제 성능을 대표하지 않는다. raw private RFP, private eval case, per-case trace는 저장소에 커밋하지 않는다.

## 2. Smoke Cases

`eval/config.yaml`은 작은 fixture corpus 위에서 여러 preset을 실행한다. 핵심 row는 다음 계약을 유지한다.

- `naive_baseline`: ADR 0001 baseline invariant
- `full`: metadata-first, rerank, verifier/retry가 켜진 기본 비교 대상
- `no_metadata_first`, `no_rerank`, `no_verifier_retry`: 주요 component ablation
- `retrieval_only`, `single_chunk`, `random_retrieval`: retrieval metric과 floor 확인
- `full_llm`, `full_llm_metadata`: opt-in LLM surface의 stub/deterministic wiring 확인

CI는 이 config로 `reports/eval_summary.json`이 생성되고, latency SLO가 통과하며, metric schema가 유지되는지만 확인한다.

## 3. Metrics

| Metric Group | Examples | Smoke Purpose | Private/Internal Purpose |
|---|---|---|---|
| Retrieval quality | `chunk_recall@k`, MRR, nDCG, rerank delta | 검색(retrieval) metric 산출 확인 | 검색 품질 비교와 reranker/embedding decision |
| Answer quality | accuracy, groundedness, format compliance, abstention outcome | scorer wiring과 edge-case 회귀 확인 | 답변 품질(answer quality)과 hardcase 분석 |
| Citation / evidence | citation precision, claim-citation alignment, evidence coverage | 인용(citation)·근거(evidence) artifact 생성 확인 | reviewer-friendly evidence verification |
| Latency | p50/p95, stage latency, retry cost | CI latency budget 확인 | 운영 trade-off와 SLO 분석 |

Bootstrap CI와 paired delta는 private/internal eval aggregate에서 성능 claim을 검증할 때 사용한다. 공개 fixture smoke 숫자는 headline metric으로 사용하지 않는다.

## 4. Reproducibility

공개 fixture smoke는 네트워크 호출과 private data 없이 실행되어야 한다.

```bash
bash scripts/smoke.sh
python3 scripts/check_latency_slo.py --config eval/config.yaml --summary reports/eval_summary.json
python3 -m pytest -m "not slow" -q
```

수동으로 같은 경로를 확인하려면 다음처럼 실행한다.

```bash
python3 scripts/build_index.py \
  --input_dir eval/fixtures/smoke_rfp/raw \
  --output_dir data/index \
  --embedding_backend hashing

python3 eval/run_eval.py \
  --config eval/config.yaml \
  --index_dir data/index \
  --output_dir reports
```

## 5. Boundary

| 항목 | Public fixture smoke | Private/internal eval |
|---|---|---|
| 문서 원본 | `eval/fixtures/smoke_rfp/raw/` | 커밋 금지 |
| 평가 케이스 | `eval/config.yaml`의 smoke cases | local-only config |
| 케이스별 예측 | `reports/` 아래 local-only | local-only |
| Aggregate 집계 | smoke schema 확인용 | 성능 판단과 reviewer evidence |
| CI gate | `make smoke`, `bash scripts/test.sh` | private data 요구 금지 |

전체 정책 전문은 [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)를 따른다.

## 6. Related Docs

- [`eval/eval_scoring_guide.md`](../../eval/eval_scoring_guide.md) — 채점 가이드
- [`docs/benchmarking.md`](../benchmarking.md) — benchmark/harness artifact 정책
- [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md) — 비공개 aggregate 정책
- [ADR 0003](../adr/0003-structured-answer-citation-contract.md) — 답변/인용 계약
- [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md) — eval split 정책
