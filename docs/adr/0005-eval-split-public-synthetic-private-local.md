# 0005: Eval 분리 — public fixture smoke vs private/internal eval

- **Status**: accepted
- **Date**: 2026-05-11
- **Updated**: 2026-05-24
- **Related**: [`eval/config.yaml`](../../eval/config.yaml), [`eval/real_config.example.yaml`](../../eval/real_config.example.yaml), [`eval/fixtures/smoke_rfp/raw`](../../eval/fixtures/smoke_rfp/raw), [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md), [`docs/real-data/private-hardcase-benchmark.md`](../real-data/private-hardcase-benchmark.md), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md)

## TL;DR

- 공개 저장소에는 작은 public fixture smoke eval만 둔다.
- public fixture smoke는 CI 재현성(reproducibility), wiring, latency SLO, metric schema를 확인하는 용도다.
- 실제 성능 평가는 저장소에 커밋하지 않는 private/internal eval set과 aggregate-only evidence artifact를 기준으로 한다.

## 배경

평가에는 서로 다른 두 요구가 있다.

- **공개 재현성.** repo clone만으로 secret, paid API, 비공개 RFP 없이 eval framework와 CI wiring이 동작해야 한다.
- **정직한 성능 신호.** 실제 RFP 성능은 공개 fixture가 아니라 private/internal eval set에서 측정해야 한다. 공개 가능한 작은 fixture는 분포·난이도·문서 다양성이 제한되어 성능 benchmark 역할을 할 수 없다.

단일 공개 데이터셋으로 두 목적을 모두 만족시키면 reviewer에게 과한 신호를 준다. 따라서 공개 fixture는 smoke test로만 쓰고, 성능 주장은 private/internal aggregate evidence에 연결한다.

## 결정

두 eval 표면을 분리한다.

- **Public fixture smoke**: `eval/fixtures/smoke_rfp/raw` + `eval/config.yaml`. 커밋 가능하고 네트워크 없이 CI에서 실행한다. 목적은 eval framework, retrieval metrics, answer metrics, citation/evidence metrics, latency logging, trace artifact가 계속 살아 있는지 확인하는 것이다.
- **Private/internal eval**: `eval/real_config.example.yaml`가 scaffold 역할을 하며 실제 config/corpus는 git 외부에 둔다. 실제 성능 평가는 이 표면에서 실행하고, 커밋 가능한 산출물은 aggregate-only 보고서와 provenance만 허용한다.

모든 새 eval 표면은 둘 중 하나로 분류해야 한다.

- public fixture smoke: 공개 가능한 작은 fixture, benchmark 표현 금지
- private/internal eval: raw data와 per-case output은 local-only, aggregate evidence만 commit-safe

## 결과

**유지되는 것**

- retrieval quality metrics
- answer quality metrics
- citation accuracy / evidence verification
- latency logging and SLO check
- private/internal eval hook
- fixture 기반 smoke test
- reviewer-friendly aggregate evidence artifact

**의도적으로 제거한 것**

- public data를 primary benchmark처럼 보이게 하는 dataset, generator, aggregate report, judge aggregate, README metric snapshot
- public fixture score를 실제 성능 주장으로 읽히게 만드는 문서 표현

## 운영 규칙

이 레포지토리는 공개 가능한 작은 fixture를 smoke test 용도로만 사용합니다. 실제 성능 평가는 레포지토리에 커밋하지 않는 private/internal eval set을 기준으로 수행하는 것을 전제로 합니다.

CI는 public fixture smoke eval과 unit test, latency budget check만 요구한다. Private/internal data는 CI 필수 조건이 아니며, raw private data는 저장소에 포함하지 않는다.

## 대안

- **공개 fixture를 benchmark로 유지.** Reject: 공개 가능한 작은 데이터가 성능 증거처럼 보이며 평가 story의 신뢰도를 약화한다.
- **비공개 평가만 유지.** Reject: clone 후 eval framework와 CI 재현성을 확인할 수 없다.
- **단일 config에서 public/private를 조건부 로드.** Reject: PR gate와 실제 성능 평가의 목적이 달라 reviewer가 결과를 오해하기 쉽다.
