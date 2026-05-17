<!--
CLAUDE.md + docs/engineering-governance.md 규약. 각 섹션 순서대로 채움.
해당 없으면 "N/A + 한 줄 사유" — 섹션 삭제 금지.
-->

## 1. 무엇을 왜 바꿨는가

<!--
한 문단. 아래 `Closes #N` 은 **필수** (ADR 0007). 브랜치명의 issue 번호와
일치해야 함 (예: `feat/issue-79-foo` → `Closes #79`). Branch & Issue
Convention CI gate 가 누락·불일치 시 머지 차단.
-->

Closes #

## 2. 영향 파일

<!--
Bullet list. 다음 항목은 load-bearing 으로 표시
(단일 출처: scripts/_governance.py):
rag_core.py, rag_retrieval.py, rag_verifier.py, rag_answer.py, rag_query.py,
ingestion.py, visual_ingestion.py, eval/, api/, docs/adr/, scripts/build_index.py
-->

## 3. 리스크

<!-- 가장 가능성 높은 깨짐 경로. 그것을 배제하기 위해 무엇을 확인했는가. -->

## 4. 테스트

<!--
신규 동작을 검증하는 테스트는? Behavior change 는 변경 전 fail / 변경 후 pass
하는 테스트 최소 1개 필수. 출시된 버그용 regression 은 tests/test_*_regression.py
(pattern: tests/test_retrieval_loop_regression.py).
테스트 미추가 시 사유 명시.
-->

## 5. Eval 영향

<!--
CI eval delta 예상은? RAG 외 변경이면 "All `·`" 답변 가능 — 명시할 것.
-->

### 5b. Real-data delta

<!--
Load-bearing path 변경 시 필수
(rag_core.py, rag_retrieval.py, rag_verifier.py, rag_answer.py, rag_query.py,
ingestion.py, visual_ingestion.py, eval/, api/, docs/adr/, scripts/build_index.py).
`make real-eval-delta` 집계 표 첨부 또는 명시:
"검색/검증 path 동작 변화 없음."
ADR 0005 참조. 합성 CI delta 만으로는 #69 intended-abstention regression 을
놓쳤다. §5b CI gate (scripts/check_branch_and_issue.py --check-5b) 가 강제.
README metric sync 는 pr-eval.yml (issue #739) 가 별도 gate — eval surface
변경 후 `python scripts/update_readme_metrics.py` 실행.
-->

## 6. 하위 호환

<!--
기존 계약/스키마/CLI flag/doc link 깨짐? Answer-contract 변경 (ADR 0003) 은
`schema_version` bump 필수. yes 면 마이그레이션 경로는?
-->

## 7. 범위 외

<!-- 알아챘으나 의도적으로 안 고친 것. -->

<!--
선택: **`live-judge-please`** 라벨 부착 시 `.github/workflows/pr-judge.yml`
(ADR 0043) 실행. live LLM-judge 1회 수행 후 RAGAS 집계를 PR 코멘트로 게시.
push 후 갱신은 라벨 재부착 (Goodhart guard).
-->
