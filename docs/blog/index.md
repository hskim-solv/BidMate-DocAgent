---
layout: page
title: 엔지니어링 블로그
permalink: /blog/
---

BidMate-DocAgent의 엔지니어링 결정과 그 *왜*를 정리한 시리즈입니다. 코드와 ADR이 *무엇*을 했는지 말한다면, 이 블로그는 *왜 그렇게 결정했는가*와 *어떻게 측정해 검증했는가*를 다룹니다.

## Phase 4 시리즈

### 1. [Extractive를 1급 baseline로 유지하는 이유](./2026-05-extractive-baseline/)

LLM 합성이 화려해 보여도 **extractive baseline을 그대로 살려두고**, 새 기법은 baseline 옆에 *측정 가능한 ablation*으로만 추가한다는 원칙. citation precision `0.512 → 0.905`(95% CI 분리)이라는 정량 근거와, synthetic CI가 놓친 real-data 회귀(이슈 #69) 사례를 통해 이 원칙이 *비용을 정당화한 결정*임을 보입니다.

### 2. [Public synthetic + Private real, 두 평가 surface](./2026-05-public-synthetic-private-real/)

재현 가능성과 honest signal은 같은 평가 surface로 동시에 충족하기 어렵습니다. 두 surface를 *코드 강제 경계*로 유지해 둘 다 가지는 방법(.gitignore + pre-commit hook + script-level allowlist의 3중 방어). 이슈 #69 회귀가 *왜 공개 평가에서 잡히지 않고 실데이터에서 잡혔는지*의 메커니즘을 정량으로 설명합니다.

### 3. 실패 분류로 백로그 생성하기 (준비 중)

발견한 실패를 ad-hoc하게 수정하는 대신 **분류 → 카테고리별 root cause → 코드 위치 → Impact/Effort grid → GitHub 이슈**로 매핑하는 방법론. C6 false abstention → 이슈 #69, C4 follow-up loss → 이슈 #71, C2 ambiguity → 이슈 #72 매핑 walk-through.

## 관련 자료

- 저장소 README: [github.com/hskim-solv/BidMate-DocAgent](https://github.com/hskim-solv/BidMate-DocAgent)
- ADR 인덱스: [`docs/adr/README.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/README.md)
- 실패 분류 본문: [`docs/real-data-failure-taxonomy.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/real-data-failure-taxonomy.md)
