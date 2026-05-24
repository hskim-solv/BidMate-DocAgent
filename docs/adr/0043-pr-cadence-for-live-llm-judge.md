# 0043: PR-time live LLM judge workflow retired

- **Status**: superseded by 0005
- **Date**: 2026-05-14
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0006](./0006-llm-judge-on-real-data-only.md)
- **Deciders**: hskim

## Context

이 ADR은 PR label로 live LLM judge를 실행하고 public aggregate artifact를 남기는 workflow를 다뤘다. public fixture smoke / private internal eval split으로 평가 경계를 갱신하면서 해당 public judge workflow와 aggregate artifact는 제거됐다.

## Decision

PR-time public judge workflow는 retired 처리한다.

- CI는 public fixture smoke eval, unit tests, latency SLO만 실행한다.
- 실제 LLM judge 또는 reviewer-facing evidence는 private/internal eval set과 aggregate-only artifact에서 다룬다.
- public fixture smoke 결과를 benchmark나 ranking signal로 커밋하지 않는다.

## Consequences

- PR CI는 private data와 external API key를 요구하지 않는다.
- Public fixture smoke는 평가 프레임워크의 재현성 확인만 담당한다.
- Private/internal eval hook은 유지되며, 실제 성능 평가는 commit boundary 밖의 eval set 기준으로 수행한다.

## Verification

<!-- verifies-key: .github/workflows/pr-eval.yml:name -->
<!-- verifies-key: eval/config.yaml:cases -->
