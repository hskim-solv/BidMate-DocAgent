# 엔지니어링 거버넌스

엔지니어링 작업이 본 저장소를 어떻게 흘러가는지 안내하는 **단일 진입점**. 규칙서 ([`CLAUDE.md`](../CLAUDE.md)), 결정 기록 ([`docs/adr/`](./adr/README.md)), 테스트, 평가, reviewer 문서를 묶는다. 신규 기여자 또는 reviewer 온보딩은 여기서 시작.

## 무엇이 어디에 있나

| 관심사 | 단일 출처 | 비고 |
|---|---|---|
| 코딩 & 리뷰 규칙 | [`CLAUDE.md`](../CLAUDE.md) | Pre-PR 체크리스트, 금지 shortcut, 성능 기대치 |
| Multi-agent 조율 | [`docs/multi-agent-ownership.md`](./multi-agent-ownership.md) | 7-way 소유권, `rag_core.py` lock holder, 병행 작업 충돌 해결 |
| Load-bearing 결정 | [`docs/adr/`](./adr/README.md) | 결정 당 짧은 파일 1개, status 추적 |
| 동작 계약 | [ADR 0003](./adr/0003-structured-answer-citation-contract.md), [`docs/agentic/answer-policy.md`](./agentic/answer-policy.md) | 답변 JSON shape, `schema_version`, status 값 |
| Eval 표면 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`eval/config.yaml`](../eval/config.yaml), `eval/*.example.yaml` | 공개 합성은 commit, 비공개 local 은 `.gitignore` |
| Reviewer 메트릭 | `reports/eval_summary.json`, README headline 표 | PR eval 델타 워크플로가 PR 코멘트에 diff upsert |
| 실패 분석 | [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md), [`docs/real-data/failure-cases.md`](./real-data/failure-cases.md) | 우선순위 백로그의 원천 |
| API 데모 | [`docs/operations/api-demo.md`](./operations/api-demo.md), `api/main.py` | reviewer 놀이터, 측정 기준 아님 |
| Issue/PR triage | 본 페이지 ["Milestones & 이슈 lifecycle"](#milestones--이슈-lifecycle) | 마일스톤, stale 정책, 현재 카테고리 스냅샷 |

## 변경 lifecycle

non-trivial 변경의 체크리스트 (사람·AI 공용):

1. **Issue 열기 또는 픽업 (필수, ADR 0007).** 실패 taxonomy + 우선순위 백로그가 1차 source. [`.github/ISSUE_TEMPLATE/`](../.github/ISSUE_TEMPLATE/) 사용. 브랜치+PR 은 이 issue 번호 참조 필수 — 컨벤션 체크 (CI) 가 merge 차단
2. **ADR 필요한지 판단.** [`docs/adr/README.md`](./adr/README.md) 기준 사용. 대부분 불필요, 모호하면 issue 에 질문
3. **기존 코드 점검.** 읽은 파일, 재사용 함수, 놀란 점 명시
4. **Branch + worktree (병렬 시).** `<type>/issue-<N>[-<slug>]` (ADR 0007) — 예: `feat/issue-79-hybrid-retrieval`. Claude Code 기본 worktree 명 (`claude/<auto>`) 은 PR 전 rename (`git branch -m feat/issue-<N>-<slug>`)
5. **변경 + 테스트.** 재사용 우선, one concern per PR. 동작 변경 무 테스트 = 사고. 회귀는 `tests/test_*_regression.py`
6. **Eval 로컬 실행 (해당 시).** `make eval` 공개 합성. `main` 의 `reports/eval_summary.json` 과 비교
7. **Push + PR.** PR body 는 [`.github/pull_request_template.md`](../.github/pull_request_template.md) 채움
8. **CI 검증.** 3개 체크 (모든 PR): `Pytest` + `Eval delta vs base` + `Validate branch name + issue link` (ADR 0007, required status check)
9. **리뷰 응답.** 리뷰 중 scope 추가 금지 — follow-up issue
10. **Merge.** Squash-merge, 브랜치 삭제, worktree 정리
11. **문서 갱신** (reviewer 가 알아야 할 변경 시): README headline 메트릭, ADR status, taxonomy entry

## Milestones & 이슈 lifecycle

Open issue 는 마일스톤으로 그룹화 — 백로그가 깨끗이 스캔되고 계획 vs 보류 구분 가능. 마일스톤은 GitHub 에서 수동 관리; 아래 스냅샷은 예시, GitHub 마일스톤 페이지가 authoritative.

### 마일스톤

| 마일스톤 | 목적 | 일반적 issue 종류 |
|---|---|---|
| `v3-release` | RAG 스택 차기 릴리즈 작업 — ingestion v3, 검색·순위 변경, 신규 코어 유틸 | 동작 ship 하는 `feat`, `fix` |
| `portfolio-review-readiness` | Reviewer 폴리시: README 명확성, 케이스 스터디, 배포 산출물, 구조화 출력 docs, 분석 변형 시각화 | 포트폴리오 reviewer 대상 `docs`, `chore`, `eval` |
| `real-data-evaluation` | 비공개 100-doc real-data eval 건강성: [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md) 관측 실패, 한국어 축, 보류 회귀 | 측정 가능한 real-data 델타 ship 하는 `eval`, `fix` |

Meta/parent issue (예: #118 포트폴리오, #187 phase 향상 백로그) 는 마일스톤 미할당 — 자식 issue 가 마일스톤 보유.

### Stale 정책

- **60일 무활동** → `stale` 라벨 + "still planned? close or rescope" 코멘트. 주간 triage
- **`stale` 후 90일 무활동** → 마일스톤 포인터와 함께 close. 작업 재개 시 reopen
- **Auto-close 절대 금지** — 종결은 사람 결정, 라벨이 자동화 친화 신호

라벨/마일스톤 현재 수동 관리, GitHub Action 미연결.

### 스냅샷 (2026-05-11)

| 마일스톤 | Open issue |
|---|---|
| `v3-release` | #121, #167, #168, #170 |
| `portfolio-review-readiness` | #122, #123, #124, #125, #127, #128, #164, #172 |
| `real-data-evaluation` | #126 |

분류되지 않은 issue 는 마일스톤 없이 유지.

## 문서들의 상호 강화

```
                ┌───────────────────────────┐
                │        CLAUDE.md          │  (규칙)
                └─────────────┬─────────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        ┌──────────┐    ┌──────────┐     ┌──────────┐
        │  ADR     │    │  Test    │     │   Eval   │
        │ (왜)     │    │ (가드)   │     │ (증명)   │
        └────┬─────┘    └────┬─────┘     └────┬─────┘
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                ┌───────────────────────────┐
                │   Reviewer 문서           │
                │  (README, docs/*, PR diff)│
                └───────────────────────────┘
```

- **CLAUDE.md** = 모든 변경이 만족할 규칙
- **ADR** = load-bearing 선택의 *왜*, 향후 무의식적 반전 방지
- **Test** = 규칙·결정의 silent rot 방지
- **Eval** = 규칙·결정을 reviewer 가 읽을 수치로 변환
- **Reviewer 문서** (README, design docs, PR description, 분석 변형 report) 가 위를 가리켜 작성자 DM 없이 end-to-end 이해 가능

## 본 거버넌스가 막는 안티패턴

- **Silent 계약 drift** — 답변 필드가 사라져도 테스트가 못 잡음. *방지*: ADR 0003 + `score_answer_format` (`eval/run_eval.py`)
- **Headline 메트릭 인플레이션** — README 가 산출물 없는 숫자 주장. *방지*: `scripts/update_readme_metrics.py --check` (in `make check`) + 공개/비공개 eval 분리 (ADR 0005)
- **기준선 rot** — naive_baseline 이 import 되지만 아무도 안 돌림. *방지*: `naive_baseline` = `eval/config.yaml` 의 named 분석 변형, 매 eval run 마다 보고
- **결정 세탁** — load-bearing 선택이 리팩터 PR 에 묻힘. *방지*: CLAUDE.md Core principles 의 ADR 임계값 + [`docs/adr/README.md`](./adr/README.md); PR 템플릿이 질문 강제
- **리뷰 중 scope 증가** — "while I was here" fix 가 PR 비대화. *방지*: CLAUDE.md "one PR, one concern"; follow-up issue spawn

## Governance saves: 실제 막은 인시던트

위 목록은 *설계* — 규칙과 가드. 이 섹션은 *증거* — 실제 발생한 인시던트와 사후 추가된 hook/ADR/규칙. 거버넌스가 *있다* 가 아니라 *rent 를 냈다* 가 reviewer 의 30초 질문. 각 항목 = rent 1회.

- **#69 의도된 보류 회귀 — 합성 CI 의 real-data 사각.** 합성 n=42 CI 델타는 녹색이었으나 비공개 100-doc real-eval 에서 근거 불충분 시 의도된 보류 손실. eval 분리 규율 ([ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md)) 은 이미 있었지만 PR 시점 gate 가 advisory. *사후 추가*: PR 템플릿 **5b (real-data 델타)** 필수 CI 체크 ([`scripts/check_branch_and_issue.py --check-5b`](../scripts/check_branch_and_issue.py), [`scripts/_governance.py`](../scripts/_governance.py) load-bearing 경로 리스트 경유 강제). `rag_*.py` / `ingestion.py` / `eval/` / `api/` / `docs/adr/` 손대는 PR 은 real-data aggregate 첨부 또는 behavior-no-op 사유 명시 필요

- **Stacked-PR child auto-close on `--delete-branch` merge.** base 브랜치를 `gh pr merge --delete-branch` 로 머지하면서 stacked dependent PR 이 여전히 그 브랜치를 target 으로 함 → GitHub 기본 동작이 dependent PR auto-close, 진행 중 리뷰 상태 손실. *사후 추가*: [`.claude/settings.json`](../.claude/settings.json) 의 `PreToolUse` Bash matcher 가 `gh pr list --base <this-PR-head> --state open --json number` 비어있지 않을 때 `gh pr merge --delete-branch` 거부. 명령이 GitHub 에 도달 전 차단. 규칙 텍스트는 `CLAUDE.md > Prohibited` 에 살아남도록 명시

- **ADR 번호 worktree 충돌.** 관측 페어 3개 — 0022→0023, 0023→0025, 0029→0030 — 두 worktree 가 독립적으로 `ls docs/adr/` 에서 같은 ADR 번호 예약 후 머지 시점 충돌. 수정은 procedural (번호는 공유 자원). *사후 추가*: `CLAUDE.md > Core principles > "Reserve ADR numbers up front"` 가 dual check (`ls docs/adr/` + `gh pr list --search "ADR" --state open`) 강제 + 사용자 확인 요구 (worktree 간 직렬화)

각 인시던트 = 1회 지불된 실제 비용. 신규 인시던트 (거버넌스 갭 → 수정 → 무재발) 는 여기 추가.

## 온보딩 shortcut

신규 기여자 reading order:

1. [`CLAUDE.md`](../CLAUDE.md) — 규칙
2. 본 파일 — 규칙들의 연결
3. [`docs/adr/README.md`](./adr/README.md) + 현재 ADR 6개 훑기 — load-bearing 결정
4. [`docs/real-data/real-data-failure-taxonomy.md`](./real-data/real-data-failure-taxonomy.md) — 백로그 원천

10분 짜리 reviewer 는 step 3 부터.

## 훅 설정

### Git 훅 (opt-in, 개발자당 1회)

활성화:

    make install-hooks
    # 또는:
    git config core.hooksPath .githooks

`.githooks/` 의 2개 훅 활성:

- **`pre-commit`** — eval 분리 (ADR 0005) 비공개측 파일 포함 commit 을 **hard-block**. `.gitignore` 정렬, `git add -f` + force-path 잡음. `git commit --no-verify` 우회는 훅 allowlist 가 놓친 aggregate 산출물 의도 commit 시만 + 같은 변경에서 allowlist 수정

- **`pre-push`** — 2개 체크:
  1. **브랜치 + 이슈 컨벤션 (ADR 0007)** — 현 브랜치가 `<type>/issue-<N>[-<slug>]` 미매치 시 **hard-fail**. CI 체크의 미러, push round-trip 전 위반 표면화. `gh` 설치+인증 시 issue #N 존재 확인 추가
  2. **Real-data eval 리마인더** — 검색/검증기/eval/api 경로 touch 시 **soft-warn**, PR 템플릿 5b 의 `make real-eval-delta` 첨부 reminder. Exit 0, 차단 안 함

  `git push --no-verify` 우회는 문서화된 사유 (예: 측정된 PR 의 doc-only follow-up) 시만

### Claude Code 훅 (자동 로드)

`.claude/settings.json` commit 되어 Claude Code 자동 로드. `Edit`/`MultiEdit`/`Write` 의 **`PreToolUse`** 훅 등록 — Claude 가 load-bearing 파일 (`rag_core.py`, `ingestion.py`, `visual_ingestion.py`, `eval/`, `api/`, `docs/adr/`) 수정 직전 stderr awareness reminder. 고려할 ADR 리스트 + PR 템플릿 5b 요구사항 noting.

훅 스크립트: [`scripts/claude-hooks/pretooluse-loadbearing.sh`](../scripts/claude-hooks/pretooluse-loadbearing.sh). 차단 안 함 — 순수 awareness layer.

### Claude Code 훅 (opt-in, user-global) — plan-slug race detector

병행 worktree 의 Claude Code 세션들이 user-global 디렉터리 (`~/.claude/plans/<random-slug>.md`) 에 plan 파일 write. slug 공간은 크지만 10+ 동시 worktree 에서 충돌 0 아님 (2026-05-15 관측, issue [#779](https://github.com/hskim-solv/BidMate-DocAgent/issues/779)).

[`scripts/claude-hooks/plan-slug-race.sh`](../scripts/claude-hooks/plan-slug-race.sh) = **user-global** `PreToolUse` 훅. plan 파일 `Write` 차단 조건:

- 대상 파일 존재
- mtime 이 최근 5 min 내 (`PLAN_SLUG_RACE_THRESHOLD`, 기본 300 s)
- 처음 200 바이트가 caller cwd 와 다른 worktree slug 선언

writer 측 컨벤션: 모든 plan 파일 처음 200 자에 `` 본 plan은 worktree `<slug>` 의 deliverable. `` 같은 마커 포함 → 훅이 race 검출. 마커 없는 plan 은 차단 안 함 (false-positive 회피).

Override (다른 worktree plan 의도적 덮어쓰기): `PLAN_SLUG_RACE_THRESHOLD=0`.

훅은 **자동 등록 안 됨** (Claude Code 세션이 여러 repo 걸칠 수 있음). `~/.claude/settings.json` 에 1회 wire:

```jsonc
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "<절대경로>/scripts/claude-hooks/plan-slug-race.sh"
          }
        ]
      }
    ]
  }
}
```

회귀 커버리지: `tests/test_plan_slug_race_hook_regression.py`.
