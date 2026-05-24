# Ablation Results

이 문서는 공개 fixture smoke와 private/internal eval aggregate의 역할을 구분한다. 공개 fixture 결과는 성능 benchmark가 아니라 evaluation harness가 정상 동작하는지 확인하는 smoke artifact다.

이 레포지토리는 공개 가능한 작은 fixture를 smoke test 용도로만 사용합니다. 실제 성능 평가는 레포지토리에 커밋하지 않는 private/internal eval set을 기준으로 수행하는 것을 전제로 합니다.

## Public Fixture Smoke

CI는 `eval/fixtures/smoke_rfp/raw/`와 `eval/config.yaml`을 사용해 다음을 확인한다.

- `naive_baseline`, `full`, 주요 ablation row가 모두 실행된다.
- 검색(retrieval) 지표, 답변 품질(answer quality) 지표, 인용/근거(citation/evidence) 지표, latency 지표가 `reports/eval_summary.json`에 남는다.
- `scripts/check_latency_slo.py`가 fixture smoke run의 latency budget을 검증한다.
- 네트워크 호출과 private data 없이 deterministic하게 통과한다.

## Private/Internal Aggregate

실제 성능 판단은 private/internal eval set의 aggregate-only artifact를 기준으로 한다. 원문 RFP, per-case prediction, trace는 커밋하지 않는다.

Reviewer-facing evidence는 다음 형태로 남긴다.

- aggregate metric table
- paired delta 또는 confidence interval
- failure-mode taxonomy 요약
- citation/evidence verification summary
- latency and retry-cost summary

## Metrics

| Axis | Metrics |
|---|---|
| Retrieval quality | `chunk_recall@k`, MRR, nDCG, rerank delta |
| Answer quality | accuracy, groundedness, answer format compliance, abstention outcome |
| Citation / evidence | citation precision, claim-citation alignment, evidence coverage |
| Latency | p50/p95, stage latency, retry cost |

삭제된 public judge, public aggregate history, public ranking artifacts는 더 이상 evaluation story의 일부가 아니다. 관련 정책은 [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)를 따른다.
