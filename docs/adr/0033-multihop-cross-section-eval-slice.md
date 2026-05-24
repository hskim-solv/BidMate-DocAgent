# 0033: Multi-hop public generation slice retired

- **Status**: superseded by 0005
- **Date**: 2026-05-13
- **Deciders**: hskim
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0032](./0032-eval-saturation-routed-subset.md)

## Context

이 ADR은 public multi-hop query generation slice를 별도 eval surface로 추가하려는 결정을 담았다. 현재 저장소는 public generated eval data를 유지하지 않고, 공개 가능한 작은 fixture를 smoke test 용도로만 둔다.

## Decision

Public multi-hop generation slice, generator, config, dataset artifact는 retired 처리한다.

- Public fixture smoke는 `eval/config.yaml`의 작은 deterministic case set으로 제한한다.
- Multi-hop 또는 complex reasoning 성능 평가는 private/internal eval set에서 aggregate-only artifact로 다룬다.
- Public fixture 결과를 primary benchmark처럼 표현하지 않는다.

## Consequences

- CI가 generated public eval data나 external API를 요구하지 않는다.
- Core eval framework와 retrieval/answer/citation/latency metrics는 유지된다.
- Private/internal eval hook은 복잡 질의 slice를 계속 수용할 수 있다.

## Verification

<!-- verifies-key: eval/config.yaml:cases -->
<!-- verifies-key: harness/smoke.yaml:id -->
