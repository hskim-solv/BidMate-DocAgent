# Multi-agent 소유권 모델

> **추적: [#245](https://github.com/hskim-solv/BidMate-DocAgent/issues/245).**
> 역할별 owner: [#238](https://github.com/hskim-solv/BidMate-DocAgent/issues/238) · [#239](https://github.com/hskim-solv/BidMate-DocAgent/issues/239) · [#240](https://github.com/hskim-solv/BidMate-DocAgent/issues/240) · [#241](https://github.com/hskim-solv/BidMate-DocAgent/issues/241) · [#242](https://github.com/hskim-solv/BidMate-DocAgent/issues/242) · [#243](https://github.com/hskim-solv/BidMate-DocAgent/issues/243) · [#244](https://github.com/hskim-solv/BidMate-DocAgent/issues/244)

## 왜 필요한가

RAG 파이프라인은 단계별 (ingestion → 검색 → 계획 → 검증 → 답변 → eval) 로 나뉘지만, 허브 모듈 [`rag_core.py`](../rag_core.py) (~4,227 LOC) 가 검색·계획·검증·청킹·답변 조립을 한 파일에 집중하고 26개 파일이 이를 import. 14개 ADR 이 계약 (답변 스키마, 기준선 보존, eval 분리, 근거 경계) 을 고정. [`CLAUDE.md`](../CLAUDE.md) 는 "one PR, one concern" + stacked-PR 규율 요구.

여러 agent 가 병행 작업 시 3개 충돌 지점:

1. 단일 파일 `rag_core.py`
2. 답변 dict 스키마 (ADR 0003) — `eval/`, `api/`, `demo/` 의 모든 소비자가 의존
3. `eval/config.yaml` — `naive_baseline` preset 보존 의무 (ADR 0001)

해법: **ADR 소유권** + **허브 lock-holder** — ADR cluster 당 agent 1명, `rag_core.py` 변경은 단일 owner 경유.

## 원칙

1. **ADR 소유권.** agent 1명 = ADR 계약 1개 이상의 단독 저자. 해당 ADR 수정은 그 agent 의 PR 으로만
2. **허브 lock holder.** `rag_core.py` 는 Pipeline Core owner 만 수정. 다른 owner 는 hook, callback, `run_rag_query` public surface 경유
3. **Additive only.** 신규 기능은 분석 변형 또는 확장 preset (ADR 0001/0011/0014). 추출형 기준선은 절대 교체 금지
4. **Stacked PR.** 의존 작업은 상위 PR 위로 rebase, `gh pr create --base <upstream>`. 독립 작업은 `main` 으로 직접

## 7개 소유권 역할

### 1. Pipeline Core — [#238](https://github.com/hskim-solv/BidMate-DocAgent/issues/238)

- **파일**: [`rag_core.py`](../rag_core.py) (청킹 889–1100, 계획 1750–2025, 검색 2027–2320, 검증 2528–2750, 답변 조립 2749–2950 + 4155–4190)
- **ADR**: 0001 (기준선), 0002 (메타데이터 우선), 0003 (답변 계약), 0004 (검증기·재시도), 0008 (근거 경계), 0010 (하이브리드 검색)
- **금지**: `pipeline_cli_choices()` 에서 `naive_baseline` 제거; `run_rag_query` 반환 dict 키 무단 변경; 답변 계약 변경 시 `schema_version` bump 누락

### 2. Ingestion — [#239](https://github.com/hskim-solv/BidMate-DocAgent/issues/239)

- **파일**: [`ingestion.py`](../ingestion.py), [`visual_ingestion.py`](../visual_ingestion.py), [`rag_normalize.py`](../rag_normalize.py), [`text_normalize.py`](../text_normalize.py)
- **ADR**: 0008 (근거 경계 — 입력측)
- **범위 예시**: 신규 문서 포맷 (HWPX 등), OCR/visual 추출 개선, 한국어 정규화 규칙, 파서 메트릭

### 3. Synthesis — [#240](https://github.com/hskim-solv/BidMate-DocAgent/issues/240)

- **파일**: [`rag_synthesis.py`](../rag_synthesis.py); `rag_core.py` 안 synthesis 훅 1개 (Pipeline Core 경유)
- **ADR**: 0011 (LLM synthesis additive)
- **금지**: `claims`/`citations` 를 LLM 에서 생성 (추출형 유지 — ADR 0003+0011). Synthesis 는 opt-in 유지, 기본 활성 금지

### 4. Evaluation — [#241](https://github.com/hskim-solv/BidMate-DocAgent/issues/241)

- **파일**: [`eval/`](../eval/) 전체, [`scripts/run_real_eval_delta.py`](../scripts/run_real_eval_delta.py), [`scripts/compare_eval.py`](../scripts/compare_eval.py), [`scripts/compare_external_baselines.py`](../scripts/compare_external_baselines.py), [`scripts/leaderboard.py`](../scripts/leaderboard.py), [`scripts/update_readme_metrics.py`](../scripts/update_readme_metrics.py), [`scripts/write_real_eval_baseline.py`](../scripts/write_real_eval_baseline.py), [`scripts/write_synthetic_history.py`](../scripts/write_synthetic_history.py)
- **ADR**: 0005 (eval 분리), 0006 (real-only judge), 0009 (외부 baseline), 0012 (합성 judge stub-default), 0014 (RAGAS additive)
- **금지**: `eval/config.yaml` 에서 `naive_baseline` 제거 (ADR 0001); 공개 CI 에서 live LLM judge 기본 활성 (ADR 0012); 비공개 real-data 산출물 commit (ADR 0005)

### 5. Observability — [#242](https://github.com/hskim-solv/BidMate-DocAgent/issues/242)

- **파일**: [`rag_observability.py`](../rag_observability.py); `rag_core.py` trace 훅 삽입점 (Pipeline Core 경유)
- **ADR**: 0013 (pluggable observability)
- **범위 예시**: 신규 trace backend (Otel exporter, custom sink), redaction 정책, span enrichment

### 6. API & Demo — [#243](https://github.com/hskim-solv/BidMate-DocAgent/issues/243)

- **파일**: [`api/main.py`](../api/main.py), [`app.py`](../app.py), [`demo/`](../demo/)
- **ADR**: 없음 — `run_rag_query` public surface 만 소비
- **제약**: `run_rag_query` 반환 dict 키만 사용. `rag_core.py` 내부 헬퍼 import 금지; 신규 인터페이스 필요 시 Pipeline Core owner 경유

### 7. Infra & CI — [#244](https://github.com/hskim-solv/BidMate-DocAgent/issues/244)

- **파일**: [`.github/workflows/`](../.github/workflows), [`.githooks/`](../.githooks), [`scripts/check_branch_and_issue.py`](../scripts/check_branch_and_issue.py), [`.github/pull_request_template.md`](../.github/pull_request_template.md), [`.github/ISSUE_TEMPLATE/`](../.github/ISSUE_TEMPLATE), [`.claude/settings.json`](../.claude/settings.json)
- **ADR**: 0007 (issue-linked 브랜치 명명)
- **범위 예시**: 신규 CI gate (예: `schema_version` assertion), pre-commit/pre-push 훅 추가, PR/issue 템플릿 갱신

## 충돌 해결 규칙

- **`rag_core.py` 동시 편집**: Pipeline Core owner 가 단독 lock holder. 다른 owner 가 hook/public surface 로 안 되는 hub 변경 필요 시 Pipeline Core 경유 interface-change PR 먼저 → downstream PR 은 `gh pr create --base` 로 stack
- **답변 dict 스키마 변경 (ADR 0003)**: 항상 standalone PR — ADR 수정 + `schema_version` bump + eval/api/demo 소비자 broadcast. feature 작업과 묶지 않음
- **`eval/config.yaml`**: Evaluation owner 단독. 다른 owner 는 신규 분석 변형 preset 요청, 직접 편집 금지
- **`docs/adr/` 파일**: 해당 영역 owner 가 신규 ADR 작성. 기존 ADR 파일 삭제·이름변경 금지 — Status 블록에 **Superseded** 표시

## 시나리오 → owner 매핑

| 시나리오 | owner | Stacking |
| --- | --- | --- |
| 신규 검색 backend (예: ColBERT) | Pipeline Core + Evaluation | Eval PR 이 Pipeline Core PR 위로 stack |
| 신규 문서 포맷 (예: HWPX) | Ingestion | Standalone |
| LLM-judge / RAGAS 메트릭 개선 | Evaluation | Standalone |
| 신규 데모 화면 또는 Colab 노트북 | API & Demo | Standalone |
| 신규 CI gate (예: `schema_version` assertion) | Infra & CI | Standalone |
| 답변 스키마 확장 | Pipeline Core → API & Demo + Evaluation | 소비자 PR 이 스키마 PR 위로 stack |
| 신규 Otel exporter | Observability | Standalone |

## 검증

매 PR 전: `make smoke` + `bash scripts/test.sh`. load-bearing 파일 (`rag_core.py`, `ingestion.py`, `visual_ingestion.py`, `eval/`, `api/main.py`) 변경 시 `make real-eval` + `make real-eval-delta` + PR 템플릿 5b 채움.

CI gate: [`pr-eval.yml`](../.github/workflows/pr-eval.yml), [`branch-and-issue-check.yml`](../.github/workflows/branch-and-issue-check.yml). 답변 계약 PR 은 추가로 `schema_version` 증가 + ADR 0003 갱신 확인.

## 참고

- [`docs/engineering-governance.md`](engineering-governance.md) — 워크플로 맵
- [`docs/adr/README.md`](adr/README.md) — ADR 인덱스
- [`CLAUDE.md`](../CLAUDE.md) — 저장소 컨벤션
