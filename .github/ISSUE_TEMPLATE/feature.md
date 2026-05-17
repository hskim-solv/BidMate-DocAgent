---
name: Feature / enhancement
about: 신규 기능 또는 기존 기능 개선.
title: "[feat] "
labels: enhancement
---

<!--
ADR 0007 에 따라 모든 PR 은 issue 와 연결. 이 issue 를 먼저 열고,
브랜치명은 `feat/issue-<N>-<slug>` 로.
-->

## 동기

<!-- 사용자/reviewer 가 보는 어떤 문제를 푸는가? 해당 failure taxonomy
항목, ADR, 또는 이전 PR 링크. -->

## 제안 범위

<!-- 동기를 충족하는 가장 작은 변경의 bullet list. "One PR, one concern" —
bullet 이 ~3개 넘으면 issue 분할 고려. -->

## 범위 외

<!-- 이 issue 가 의도적으로 안 건드릴 것. 구현자가 "여기 온 김에" scope creep
저항하는 데 도움 (CLAUDE.md). -->

## 완료 신호

<!-- reviewer 가 완료를 어떻게 알 것인가. 메트릭, test 명, demo 명령, 또는
artifact. RAG 관련이면 움직일 eval metric 명시 (governance-only 면
"검색/검증 path 동작 변화 없음"). -->

## 영역

<!-- 해당되는 것 모두 체크. 단, 구현자의 PR 은 single concern 선언. -->

- [ ] Ingestion (`ingestion.py`, `visual_ingestion.py`)
- [ ] Retrieval / verifier / answer (`rag_core.py`)
- [ ] Eval / metrics (`eval/`)
- [ ] API demo (`api/`)
- [ ] Docs / governance
- [ ] Other:
