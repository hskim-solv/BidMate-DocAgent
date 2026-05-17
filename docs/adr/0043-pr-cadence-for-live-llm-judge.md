# 0043: live LLM-judge 신호를 위한 PR 단위 cadence (label-gated workflow)

- **Status**: accepted
- **Date**: 2026-05-14
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) §
  "LLM-judge gate layers" · [ADR 0012](./0012-llm-judge-on-public-synthetic.md) ·
  [ADR 0004](./0004-verifier-retry-policy.md) · issue #722
- **Deciders**: hskim

## TL;DR

- `live-judge-please` 라벨 부착 시 발화되는 별도 PR workflow 추가
- 결과는 PR 코멘트 + artifact, 자동 커밋 없음 — ADR 0005 경계 보존
- `labeled` 트리거 (synchronize 제외) 로 Goodhart 압력 방지

## 배경

[ADR 0012](./0012-llm-judge-on-public-synthetic.md) § *Cadence* 는 다음을 명시:

> *"실제 신호를 원하는 개발자는 live 백엔드로 `make synthetic-judge` 를 수동 실행하고, 커밋된 aggregate diff 를 PR 에 첨부하며, reviewer 는 렌더된 표를 읽는다."*

작동하지만 강제 메커니즘이 없다. 실제로는:

- Reviewer 가 on-demand 로 live judge 실행을 *요청* 할 수 없음 — 저자 기억에 의존
- 저자가 잊거나, 신호 변화가 없을 것 같은 작은 PR 에서 skip
- 본 변경 세트에 대해 live run 이 *수행되었는지* PR 스레드에 visible 한 기록 없음

[ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers" (Gate 2) 는 불변량 명시: *"CI 는 stub-only 실행, live 백엔드는 오프라인 opt-in."* 모든 PR-level 자동화는 이를 존중해야 한다 — 기존 `pr-eval.yml` 은 live LLM 호출하도록 수정 금지.

명시 요청 시에만 발화되는 **별도** workflow 는 Gate 2 위반 아님 — 트리거가 의도적 사람 행동 (라벨 부착) 이지, 매 커밋 자동 CI 게이트가 아니다.

## 결정

live LLM-judge 신호용 **라벨 게이트 PR workflow** 도입:

- 새 workflow 파일 `.github/workflows/pr-judge.yml` 이 PR 에 `live-judge-please` 라벨 부착 시 `labeled` 이벤트로 발화
- 저장소 시크릿 (`BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`, `BIDMATE_JUDGE_BASE_URL`) 으로 `BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible` 사용해 `make eval && make synthetic-judge` 실행
- 결과는 **PR 코멘트** (markdown 표: `n`, `faithfulness_mean`, `answer_relevance_mean`, `agreement_with_verifier`, `by_query_type` 슬라이스) + workflow artifact 업로드
- aggregate 는 저장소에 **자동 커밋되지 않음** — 저자가 신호 검토 후 별도 커밋 선택

### 불변량 보존

| 불변량 | 보존 방법 |
|-----------|---------------|
| **ADR 0004** 재현성 | `pr-eval.yml` 미변경; stub 기본값 매 push 실행 |
| **ADR 0005** 커밋 경계 | Workflow artifact 업로드만; per-case 데이터 `git push` 없음 |
| **ADR 0003** 답변 계약 | Judge 는 `run_rag_query` 로 feedback 없음; 코멘트 전용 표면 |
| **ADR 0012** cadence | 수동 opt-in 보존; 라벨 = 명시 요청, 자동 게이트 아님 |

### 필요 시크릿

| Secret | Description |
|--------|-------------|
| `BIDMATE_JUDGE_API_KEY` | OpenAI 호환 judge endpoint API 키 |
| `BIDMATE_JUDGE_MODEL` | 모델 식별자 (예: `claude-sonnet-4-5`) |
| `BIDMATE_JUDGE_BASE_URL` | 선택적 custom base URL (예: Anthropic-Compat) |

이 시크릿들은 이미 로컬 `make synthetic-judge` 경로가 사용 중; 본 ADR 은 새 credential 도입 안 함.

### Goodhart 가드

workflow 는 `labeled` 에서 실행되지만 `synchronize` (새 push) 에서는 안 됨. 새 push 후마다 fresh judge run 받으려면 라벨 재부착 필요. judge 신호가 저자가 마이크로 커밋으로 게임할 최적화 타겟이 되는 것 방지.

**Rebound risk (2026-05-15 추가, issue #808)**: reviewer 가 매 PR 의 *머지 직전* 에 라벨을 일상적으로 부착하면 cadence 가 "매 PR 한 번" 으로 붕괴 — Alternative (b) 가 거부한 패턴 그대로. `labeled` 트리거는 per-push 게임 형태를 차단하지만 per-merge 형태는 차단 못 함. 권장 컨벤션: PR 당 최대 **두 번** 라벨 부착 (첫 리뷰 시 1회, 가장 실질적 코멘트 해결 후 1회) + 머지 차단 게이트로 사용 금지. 컴플라이언스는 비공식 — PR 코멘트 히스토리로 visible, workflow 강제 아님.

Fork PR 은 저장소 시크릿에서 `BIDMATE_JUDGE_API_KEY` 를 기본 못 받음 (GitHub 가 fork 에서 시크릿 격리). Workflow 는 `pull_request_target` 사용하거나 `github.event.pull_request.head.repo.full_name == github.repository` 명시 확인 필요 — 구현 PR 참조.

### 위협 모델

| Risk | Mitigation | Residual risk |
|------|------------|---------------|
| Fork PR head 커밋이 저장소 시크릿 읽음 | Workflow 가 `pull_request` 사용 (not `pull_request_target`); GitHub 기본값이 fork head 에서 시크릿 격리 | Trust 경계는 GitHub event-isolation 정책에 위임 — 본 repo 별도 검증 안 함 |
| Maintainer 가 적대적 fork PR 에 `live-judge-please` 부착 | 위와 동일 — `pull_request` 이벤트가 fork 커밋 컨텍스트에서 실행되지만 시크릿 없음 | Maintainer 가 라벨 부착 전 diff 읽어야 함 (비공식) |
| Workflow YAML 이 미래 변경에서 silent 약화 (예: `pull_request` → `pull_request_target`) | `tests/test_pr_judge_workflow_regression.py` 가 fork-guard 라인 string-match assertion | String-match ≠ runtime security audit — workflow 수정 시 `actionlint` + 위협 모델 재검토 필요 |
| 저장소 시크릿이 PR 코멘트 / artifact 로 누출 | 코멘트 렌더러 (`scripts/render_judge_comment.py`) 가 aggregate 필드만 작성; API 키 절대 안 씀 | 렌더러 변경은 자체 리뷰 필요 |

String-match 회귀 테스트는 우발적 약화에 대한 회귀 게이트지 보안 검증 아님. 위의 위협 모델을 권위 있는 출처로 취급; 테스트는 여러 tripwire 중 하나.

#### 라벨 권한

| Question | Answer |
|----------|--------|
| `live-judge-please` 부착 가능자? | 저장소에 Triage 이상 권한 있는 사용자 (GitHub 기본 라벨 관리) |
| 라벨 부착에 코드 리뷰 승인 필요? | 아니오 — 라벨과 리뷰는 독립 표면 |
| Write 권한 contributor 가 자기 fork PR 에 라벨 부착하면? | Workflow 가 fork head 컨텍스트에서 실행되지만 **시크릿 없이** — `pull_request` 이벤트가 시크릿 격리 |
| 적대적 PR 이 라벨 spam 으로 시크릿 유출 가능? | 아니오 — 라벨 상태 무관하게 시크릿이 fork 컨텍스트에 노출 안 됨 |

프로젝트가 live-judge workflow 가 `pull_request_target` 통해 시크릿 받는 모델로 이동하면 (예: fork PR 커버리지 지원) 위 표가 더 이상 적용 안 되며 위협 모델 새 ADR 필요.

### 운영 제약

v1 에서 의도적으로 열어둔 정책 결정; 미래 운영자가 갭 재발견 안 하도록 문서화.

| 제약 | v1 정책 | 재방문 시점 |
|-----------|-----------|-----------------|
| **Judge 모델** | `BIDMATE_JUDGE_MODEL` env var 로 운영자 제어. 본 ADR 에 upstream pin 없음 — env var 가 single source of truth | PR 간 비교가 load-bearing 되면 (예: 성능 회귀 결정) follow-up ADR 에서 모델 pin |
| **비용 ceiling** | per-PR token/달러 cap 강제 없음. 라벨 부착 빈도로 비용 bounded (reviewer-gated 이라 낮음) | 평균 PR 당 라벨 ≥ 2 또는 단일 라벨 부착이 운영자 정의 예산 초과 시 명시 cap 추가 |
| **Judge drift / 재현성** | 라벨 재부착이 새 aggregate 의 새 run 생성. 같은 PR 의 두 run 이 운영자 관찰 비결정성 (공식 spec 없음) 만큼 발산 가능 | live run 5+ 후 분산 특성화 + 비교용 `±x.x pp` tolerance 발표 결정 |

## 검토한 대안

### (a) main 만 nightly cron

최신 main 커밋 대상 nightly live judge.

*거부*: 신호가 너무 늦게 도착 — reviewer 가 PR 머지 며칠 후 aggregate 봄. 또한 단일 run 에 여러 PR 변경 혼동.

### (b) 매 PR push 자동 (feature-flag gated)

매 push 마다 live judge 실행, fork 컨텍스트에서 env var 로 skip.

*거부*: "두 번째 workflow" 로 framing 해도 ADR 0004 *"CI 가 live LLM 호출 안 함"* 정신 위반. 검색/답변 변경 없는 PR 에 push 당 토큰 비용 부당. 가장 critical: Goodhart 압력 — 저자가 실제 정확도 개선 아닌 자동 보고 점수 최대화로 prompt/검색 튜닝.

### (c) PR 템플릿 필수 필드

저자에게 PR 템플릿 "live judge results" 필드 채우게 하고 빈칸이면 CI 실패.

*거부*: 마찰 높음, 자동화 없음. 저자가 "N/A" 또는 stale 결과 paste. reviewer 부담만 추가, 신뢰성 없음.

### (d) `workflow_dispatch` 저자 트리거

저자가 GitHub Actions UI 에서 클릭하는 수동 dispatch 버튼.

*거부*: 라벨보다 발견성 낮음 (Actions UI 탐색 필요); reviewer 가 저자 없이 run 요청 못 함; 라벨 방식이 같은 명시-트리거 속성을 더 나은 UX 로 달성.

## 결과

**Wins**

- Reviewer 가 라벨 부착으로 live RAGAS 신호 요청 가능 — 저자에게 로컬 재실행 부탁 불필요
- 영구 PR 코멘트가 본 변경 세트에 live judge 가 consulted 되었는지 visible 기록 생성
- 토큰 비용 bounded: 커밋 당 아닌 라벨 부착 이벤트 당 1 run
- ADR 0004 / 0005 / 0012 불변량 모두 보존

**Costs**

- 저장소 시크릿이 repo 소유자 1회 설정 필요
- Fork PR 은 workflow 가 `pull_request_target` + 적절한 보안 검사로 작성되지 않으면 live judge 실행 못 함
- 라벨이 push 후마다 수동 재부착 필요 — 완전 자동 트리거보다 약간 마찰

**미변경**

- `make synthetic-judge` 로컬 workflow 는 개발 중 (pre-PR) live RAGAS 원하는 개발자 주 경로 유지
- `reports/synthetic_judge.aggregate.json` 스냅샷 cadence 미변경 — 개발자가 의미 있는 신호 업데이트 후 수동 커밋
