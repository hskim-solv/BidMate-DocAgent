---
layout: page
title: Engineering Blog
permalink: /blog/
---

# Engineering Blog

BidMate-DocAgent의 공개 기술 블로그 인덱스입니다. 각 글은 RFP 문서 RAG에서 반복적으로 재발한 설계 질문을 ADR, 측정 surface, 회귀 게이트와 연결해 설명합니다.

## 추천 읽기 순서

1. [Extractive를 1급 baseline로 유지하는 이유](./2026-05-extractive-baseline/) — RFP 도메인에서 citation과 abstention을 generative fluency보다 우선한 이유.
2. [0pp lift 가 가리킨 것 — 측정 surface 안의 진짜 신호](./hyde-measurement-saturation/) — HyDE 0pp 결과를 기능 실패가 아니라 measurement saturation으로 재해석한 과정.
3. [측정 도구가 자기 함정을 발견했을 때 — 5-step closed loop](./2026-05-goodhart-closed-loop/) — metric Goodhart 함정을 찾고 scorer semantics를 보정한 closed-loop 사례.
4. [Observability를 baseline 깨지 않고 추가하는 패턴](./2026-05-observability-fail-closed/) — trace backend를 additive surface로 추가하는 fail-closed 패턴.
5. [외부 시니어 리뷰 → 사실 정정 + ADR 매트릭스](./2026-05-external-review-followup/) — 외부 리뷰 권고를 코드/ADR/CI evidence로 재검증한 decision matrix.

## 30초 리뷰 경로

- Baseline과 답변 정책: [Extractive baseline](./2026-05-extractive-baseline/)
- 측정 신뢰성: [HyDE saturation](./hyde-measurement-saturation/) → [Goodhart closed loop](./2026-05-goodhart-closed-loop/)
- 운영성: [Observability fail-closed](./2026-05-observability-fail-closed/)

전체 프로젝트 개요는 [문서 홈](../index.md)과 [GitHub README](https://github.com/hskim-solv/BidMate-DocAgent)를 기준으로 확인합니다.
