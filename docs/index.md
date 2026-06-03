---
layout: home
title: BidMate Agent — Engineering Notes
---

RFP/제안요청서 문서 이해를 위한 Agentic RAG 시스템 [BidMate-DocAgent](https://github.com/hskim-solv/BidMate-DocAgent)의 엔지니어링 결정과 측정 결과를 정리한 노트입니다.

핵심 메시지는 "고급 retrieval/생성 기법을 얹는 것보다, **extractive baseline · 이중 평가 surface · 실패 분류**라는 엔지니어링 규율을 일관되게 유지한 것"이 본 프로젝트의 차별점이라는 점입니다.

## 진입점

- **[엔지니어링 블로그](./blog/)** — 측정-주도 엔지니어링 회고
  - [Extractive를 1급 baseline로 유지하는 이유](./blog/2026-05-extractive-baseline/)
  - [측정 도구가 자기 함정을 발견했을 때 — 5-step closed loop](./blog/2026-05-goodhart-closed-loop/)
  - [0pp lift 가 가리킨 것 — 측정 surface 안의 진짜 신호](./blog/hyde-measurement-saturation/)
  - [Observability를 baseline 깨지 않고 추가하는 패턴](./blog/2026-05-observability-fail-closed/)
  - [외부 시니어 리뷰 → 사실 정정 + ADR 매트릭스](./blog/2026-05-external-review-followup/)
- **[1-page Architecture deep-dive](./architecture-deep-dive/)** — 파이프라인 / ADR 매핑 / 측정 highlight 한 페이지 요약
- **[저장소 문서 인덱스](./)** — ADR, 설계 노트, 벤치마크, 평가

## 5분 리뷰 경로 (저장소 기준)

1. README의 *TL;DR* + *핵심 성능표*: [github.com/hskim-solv/BidMate-DocAgent](https://github.com/hskim-solv/BidMate-DocAgent)
2. ADR 0001 (baseline 유지), ADR 0005 (이중 평가): `docs/adr/`
3. 실패 분류: [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md)

저장소 README가 source of truth이며, 본 사이트는 narrative와 의사결정 배경을 보강합니다.
