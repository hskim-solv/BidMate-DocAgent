# CLAUDE.md

RFP 문서 이해를 위한 DocAgent 시스템. **입찰/RFP 문서 인텔리전스 전용, 범용 AI 실험장 아님.**

파이프라인: ingestion → 메타데이터 정규화 → 청킹 → 검색 → 재순위/계획 → 근거 집계 → 근거 기반 답변 → 검증 → 평가 → reviewer 문서.

자동화 표면: `.gitignore`, CI ([`pr-eval.yml`](.github/workflows/pr-eval.yml), [`branch-and-issue-check.yml`](.github/workflows/branch-and-issue-check.yml)), `.githooks/`, [`scripts/check_branch_and_issue.py`](scripts/check_branch_and_issue.py) (브랜치+이슈 컨벤션 regex 단일 출처, ADR 0007), [`.github/pull_request_template.md`](.github/pull_request_template.md), [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/), [`.claude/settings.json`](.claude/settings.json) (load-bearing 편집 awareness 훅 + stacked dependent 있을 때 `gh pr merge --delete-branch` 차단 Bash matcher). 이 파일은 자동 강제되지 않는 원칙·포인터를 담는다.

## 여기서 시작

- [`docs/engineering-governance.md`](docs/engineering-governance.md) — 워크플로 맵
- [`docs/adr/README.md`](docs/adr/README.md) — 결정 인덱스
- [`docs/multi-agent-ownership.md`](docs/multi-agent-ownership.md) — 여러 agent 가 병행 작업할 때 조율 모델
- retrieval / answer / eval 손볼 시 추가 필독: [ADR 0001](docs/adr/0001-preserve-naive-baseline.md) (기준선), [ADR 0003](docs/adr/0003-structured-answer-citation-contract.md) (답변 계약), [ADR 0005](docs/adr/0005-eval-split-public-synthetic-private-local.md) (eval 분리), [ADR 0012](docs/adr/0012-llm-judge-on-public-synthetic.md) (합성 LLM-judge)

## 저장소 맵

**Load-bearing** — 변경 시 PR 템플릿 **5b (real-data 델타)** 필수. 기계 판독 가능 단일 출처는 [`scripts/_governance.py`](scripts/_governance.py) 의 `LOAD_BEARING_PATHS` ([.githooks/pre-push](.githooks/pre-push), [scripts/claude-hooks/pretooluse-loadbearing.sh](scripts/claude-hooks/pretooluse-loadbearing.sh), `--check-5b` CI gate 가 함께 읽음). 추가/제거 시 그 파일 먼저 수정.

- `rag_core.py` — RAG 파이프라인 코어 (검색·검증·답변 오케스트레이션)
- `ingestion.py`, `visual_ingestion.py` — 문서 로딩/파싱. HWP/PDF backend = `HwpKordocLoader`/`PdfKordocLoader` (ADR 0049, `npx` 서브프로세스); `csv_text` 가 Node 부재/실패 시 무조건 fallback
- `eval/` — eval 스크립트·설정 (`eval/config.yaml` 에 `naive_baseline` 분석 변형 preset)
- `api/main.py` — FastAPI 데모 서버 (`api/` 전체가 SSoT)
- `docs/adr/` — accepted 결정 기록
- `scripts/build_index.py` — 인덱스 빌더, eval 도달 전에 분석 변형 회귀를 표면화

**Supporting** (rag_core 에서 분리된 leaf 모듈, ADR 0045 검증 — `rag_core` 로의 back-edge 0):

- `app.py` — CLI 쿼리 진입점
- `rag_vector_store.py` — `VectorStore` Protocol (#232). `BIDMATE_INDEX_BACKEND` = `memory`(기본) / `qdrant`; `pgvector` 는 Stage 3 (#176) 예약. in-memory ↔ Qdrant ranking bit-identical
- `rag_reranker.py` — `Reranker` Protocol + 기본 `CrossEncoderReranker` (#345)
- `rag_retrieval.py` — 검색 파이프라인 (#459 + #461). `retrieve_candidates`, 4 유사도 primitive, BM25, fusion·재순위·comparison balance·parent-section 재조립
- `rag_verifier.py` — 검증기 (#465, PR-J1). `verify_evidence`, topic 추출, `EVIDENCE_BOUNDARY` 상수 + 명령 패턴 regex, `neutralize_instruction_patterns` (ADR 0008)
- `rag_answer.py` — 답변 생성 (#468, PR-J2). 20 함수가 검증된 근거를 ADR 0003 답변 dict 로 변환. `schema_version: 2` 계약 유지
- `rag_query.py` — 쿼리 분석·계획 (#478, PR-J3). 15 함수, `analyze_query`/`make_plan`/`comparison_targets_for_analysis` 등
- `rag_query_expansion.py` — `QueryExpander` Protocol + 기본 `IdentityExpander` + opt-in `HyDEExpander` (#396, ADR 0023)
- `scripts/` — `build_index.py`, `update_readme_metrics.py`, `run_real_eval_delta.py` 등
- `data/raw/` → `data/index/` → `outputs/` → `reports/` (파이프라인 산출물)
- `docs/` — 설계 노트, ADR, 실패 분석, reviewer 문서

## 소통

- **사용자가 한국어로 쓰면 한국어로 응답.** 영어 프롬프트 또는 "respond in English" 명시 시만 영어. 코드·식별자·커밋 메시지·파일/디렉터리명은 영문 유지
- **2-3줄 TL;DR 후 상세.** 한 턴에 한 결정 — 여러 PR/issue/branch 를 한 메시지에 묶지 않음

## 자율성 & 승인

- **상태 변경 액션은 명시 승인 필요.** `git push`, `gh pr merge`, `gh pr create`, `git branch -D`, `gh issue create` 는 사용자 "진행/go/merge it/ok" 명시 후만. "머지?", "PR?", "?" 같은 짧은 의문은 **질문** — 답변만 하고 실행 금지
- **연쇄 부수효과** (stacked-PR merge, ADR-then-PR, multi-issue triage) 는 단계별 별도 승인

## 위임 기본값

- **non-trivial 변경 전 Plan subagent.** >1 파일 또는 >50 LOC, 또는 plan mode 진입 시 Plan subagent 우선. 오타/단일 라인만 예외
- **읽기 다발 시 Explore subagent.** Read ≥5회 누적 또는 단일 파일 >200줄 → Explore 위임
- **Shipping 경로는 commit-0 에 확정.** `ship-pr` skill (수동 게이트, ADR 예약 + stacked 안전) vs `make ship-arm` (Stop-hook 자동 ship) 둘은 mutually exclusive — 동시 활성화 금지
- 5축 ↔ 4-pillar 매핑 전체: [`docs/agent-utilization.md`](docs/agent-utilization.md). `self-review-quarterly` skill 이 해당 표 기준으로 채점

## 핵심 원칙

- **Issue first, 컨벤션 브랜치.** 모든 PR 은 issue 참조 (`Closes #N` in body) + 브랜치 `<type>/issue-<N>[-<slug>]` (ADR 0007). `branch-and-issue-check.yml` 이 PR 시점에 강제
- **새로 만들기보다 재사용.** 코딩 전 기존 구현 확인. 재사용 유틸리티 먼저 검색
- **One PR, one concern.** 범위 밖 수정 → 별도 issue/follow-up PR. 같은 도메인을 같은 날 N PR 로 분해는 valid 패턴 (예: 2026-05-15 PR-A0~A3 4-PR stacked-day). `gh pr create --base <parent>` 사용 + 부모 머지 시 `--delete-branch` 회피 (child auto-close 방지)
- **PR 크기는 surface 별.** "one concern" 은 LOC 가 아니라 surface 기준. `eval/` PR 은 200–2500 LOC 정상 (dataset + config + plot 한 묶음 = 한 concern); `docs/` PR 은 보통 <100 LOC. 2000-LOC `eval/` PR 을 크기만으로 reject 금지, 두 ADR 섞인 200-LOC `docs/` PR 은 분할. memory `project_pr_size_heuristic.md` 참조
- **동작 변경 ↔ 테스트 변경.** 테스트 없는 동작 변경은 실수로 간주. 회귀 테스트는 `tests/test_*_regression.py` (예: `tests/test_retrieval_loop_regression.py`)
- **하위 호환성.** Breaking 변경은 명시적 사유 필요. 답변 계약 (ADR 0003) 깨질 시 `schema_version` 증가
- **ADR 임계값.** load-bearing 결정 (기준선/파이프라인/답변 계약/eval 표면) 제거·교체 시 ADR 필요. **새 측정 표면** (eval 슬라이스, 리더보드 신호, self-review 축) 도입도 포함 (reviewer 가 의존할 계약 고정). 기준: [`docs/adr/README.md`](docs/adr/README.md)
- **ADR 번호 사전 예약.** ADR 작성 전 `ls docs/adr/` + `gh pr list --search "ADR" --state open` 양쪽 확인. 사용자 확인 후 파일 생성 — 동시 worktree 작업으로 0022→0023, 0023→0025, 0029→0030 충돌 반복 발생
- **LLM 코딩 편향 가드.** `karpathy-guidelines` skill ([upstream](https://github.com/multica-ai/andrej-karpathy-skills), 2026-05-15 fetch) 의 4 원칙 (Think Before / Simplicity First / Surgical Changes / Goal-Driven). **충돌 정책**: 위 프로젝트 규칙 (인시던트 유래) 이 karpathy 4 원칙 (범용) 보다 우선 — karpathy 는 프로젝트 규칙이 침묵할 때 leaning 기본값

## PR 설명

[`.github/pull_request_template.md`](.github/pull_request_template.md) 채워야 함. 모든 섹션 필수 — 삭제 대신 "N/A" + 사유. load-bearing 파일 변경 시 **5b (real-data 델타)** 가 가장 중요 — 합성 CI 델타만으로 #69 의도된 보류 회귀를 놓친 사례

## 자주 쓰는 명령

- `make install-hooks` — clone 당 1회, `.githooks/` 활성화 (pre-commit ADR 0005 경계, pre-push 브랜치/eval 체크)
- `make smoke` — 빠른 sanity check (수분, `EMBEDDING_BACKEND=hashing`)
- `bash scripts/test.sh` — `pytest -q`, CI gate 와 동일
- `make check-branch` — 현재 브랜치 ADR 0007 검증
- `make real-eval` + `make real-eval-delta` — 비공개 100-doc eval, load-bearing 변경 시 필수
- `make ship-arm` — Stop-hook 자동 ship 파이프라인 (commit → push → PR → CI → squash-merge). 게이트/단계/`STACKED=ack` 규율: [`docs/operations/auto-ship.md`](docs/operations/auto-ship.md)
- Latency 수치는 `reports/eval_summary.json` `stage_latency` 블록 — ad-hoc 측정 금지

## 금지 (자동화 비강제)

- ADR 파일 삭제/이름변경. Status 블록에 **Superseded** 표시하고 파일은 유지
- `run_rag_query` 답변 dict 를 그림자처럼 가리는 parallel pydantic/TypedDict 모델 추가 — dict 가 계약 (ADR 0003)
- `eval/config.yaml` 에서 `naive_baseline` preset 제거 (ADR 0001)
- 리뷰 중 무관한 커밋 추가 — follow-up PR 분리
- `gh pr list --base <this-PR-head> --state open --json number` 확인 없이 `gh pr merge --delete-branch` 실행. 결과가 비어있지 않으면 stacked dependent 존재 — `--delete-branch` 빼거나 child 를 main 위로 rebase 먼저. (후속 PreToolUse Bash 가드 훅이 자동화하지만, 훅 비활성화 시도 살아남도록 규칙 명시)

## Non-goals (명시 요청 없을 시)

- UI 추가, 웹 서비스 제품화
- 대규모 아키텍처 재작성
- 신규 paid-API 의존성
- 비공개 RFP 데이터 재구성

## 막혔을 때

크게 추측 금지. 대신:

1. 실패 가설 2-3개 명시
2. 재현 명령 + 관측된 에러 요약
3. 최소 수정 제안
4. 최소 수정이 안 통할 fallback 경로 설명

## 도메인 용어

- **Evidence (근거)** — 주장을 지지하는 retrieved chunk
- **Grounding (근거 연결)** — claim ↔ evidence ↔ 원문 연결 요구사항
- **Abstention (보류)** — ADR 0003 `status: insufficient`, 근거 불충분 시 일급 답변 상태. fallback/error 아님
- **Naive baseline (기준선)** — `agentic_full` 과 side-by-side 비교용 최소 파이프라인 분석 변형 preset (ADR 0001)
