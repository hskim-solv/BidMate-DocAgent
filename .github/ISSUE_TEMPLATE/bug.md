---
name: Bug report
about: 파이프라인이 잘못된 답을 내거나, 실패하거나, 회귀했다.
title: "[bug] "
labels: bug
---

<!--
ADR 0007 에 따라 모든 PR 은 issue 와 연결. 이 issue 를 먼저 열고,
브랜치명은 `fix/issue-<N>-<slug>` 로.
-->

## 무슨 일이 벌어졌나

<!-- 가장 짧은 재현 방법. 쿼리, 기대 답변, 실제 답변 (또는 stack trace). -->

## 기대 동작

<!-- 답변/로그/출력의 정답과 그 baseline 을 정한 doc/ADR/test. -->

## 다음 단계 제안

<!-- 한 문장. 어디부터 살펴볼지. 파일명 + 라인. 직접 안 고쳐도 유용. -->

## 영역

<!-- 하나 체크. 대부분의 버그는 정확히 한 영역에 속함. -->

- [ ] Ingestion (`ingestion.py`, `visual_ingestion.py`)
- [ ] Retrieval / verifier / answer (`rag_core.py`)
- [ ] Eval / metrics (`eval/`)
- [ ] API demo (`api/`)
- [ ] Docs / governance
- [ ] Other:
