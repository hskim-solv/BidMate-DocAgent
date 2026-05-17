# 0007: 이슈 연결 브랜치 네이밍을 required check 로

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`docs/engineering-governance.md`](../engineering-governance.md) §"Change lifecycle" 확장; 비공식 `claude/<auto>` worktree 네이밍 패턴 supersede
- **Deciders**: hskim

## TL;DR

- 모든 PR 브랜치는 `<type>/issue-<N>[-<slug>]` regex 강제 — CI required check.
- `scripts/check_branch_and_issue.py` 가 regex 단일 출처 — CI + 로컬 pre-push 훅 양쪽이 동일 스크립트 호출.
- PR body 의 `Closes #N` 이 브랜치 `<N>` 과 일치해야 함.

## 배경

지금까지 작업과 추적 이슈 간 강제 연결 없음:

- PR 템플릿 §1 에 `Closes #` placeholder 있으나 검증 없음([`.github/pull_request_template.md`](../../.github/pull_request_template.md))
- `git branch -a` 가 `claude/issue-<N>-<slug>`·`claude/<adj>-<name>-<hash>`(auto-named worktree)·일부 legacy `feat/<N>-<slug>` 혼재. 컨벤션은 history 로 관찰 가능하나 rule 로 명시 안 됨
- `engineering-governance.md` step 1("Open or pick an issue") 은 soft instruction. 이슈 번호 없이 PR merge 가능

결과: 추적 갭. reviewer 가 `Closes #123` grep 으로 이슈 종료 PR 을 찾을 수 없음 — 링크가 기록 안 됐다면. 더 나쁘게 `claude/<auto>` 패턴은 이슈 존재 자체를 모호하게 만듦 — 브랜치명이 intent 아닌 랜덤 단어 인코딩.

아래 새 rule 로 링크를 required + machine-checked at PR boundary.

## 결정

`main` 머지 PR 은 새 CI workflow `.github/workflows/branch-and-issue-check.yml` 가 강제하는 세 조건 만족 필요:

1. **브랜치명 컨벤션 매치:**
   ```
   ^(?:feat|fix|docs|chore|refactor|test|ci|perf|build|style)/issue-(\d+)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$
   ```
   - prefix 는 위 conventional-commit 타입 중 하나. **`claude/` 거부** — Claude Code auto-named worktree 브랜치는 PR 전 rename 필요
   - `issue-<N>` 필수; 뒤 slug 는 선택이나 human readability 위해 권장
   - 예: `feat/issue-79-senior-positioning`, `fix/issue-104`

2. **참조 이슈가 이 repo 에 존재** (state — open/closed — 미검사; follow-up 브랜치가 종료 이슈 참조 가능)

3. **PR body 에 `Closes #N`(또는 `Fixes`/`Resolves`) 포함** + 그 중 하나가 브랜치 `<N>` 과 일치. GitHub merge auto-close 와 동일 regex — 기존 UX piggyback

regex·이슈 체크·`Closes` 매칭 모두 단일 스크립트([`scripts/check_branch_and_issue.py`](../../scripts/check_branch_and_issue.py))에 위치 — CI workflow(`--pr <N>`) + 로컬 [`.githooks/pre-push`](../../.githooks/pre-push) 훅(`--branch <name>`) 양쪽 사용. regex 중복 없음, drift 없음.

### 면제

다음 브랜치 prefix 는 체크 스킵(구조상 추적 이슈 없음):

- `revert-*` — GitHub auto-generated revert
- `dependabot/*` — Dependabot PR
- `renovate/*` — Renovate PR
- `pre-commit-ci/*` — pre-commit autoupdate PR

### 강제 레이어

| 레이어 | 시점 | 우회 가능? | 검사 내용 |
|---|---|---|---|
| CI (`branch-and-issue-check.yml`) | `main` 으로 모든 `pull_request` | **No** (required status check) | 브랜치 regex + 이슈 존재 + `Closes #N` 매치 |
| 로컬 `.githooks/pre-push` | `git push` (`make install-hooks` 로 opt-in) | `--no-verify` | 브랜치 regex + (`gh` 설치 시) 이슈 존재 |

CI 가 계약. 로컬 훅은 `make install-hooks` 실행한 개발자를 위한 fast-feedback mirror.

## 결과

**Wins**

- 모든 머지 PR 이 이슈 추적 가능. `git log --grep '#'` 가 이슈의 전체 change set 발견; GitHub UI 가 머지 시 이슈 auto-close
- 브랜치명이 intent 인코딩(`feat/issue-79-…` 는 작업 종류 + 추적 대상 표현) — 랜덤 단어 아님
- PR 템플릿 `Closes #` placeholder 가 hint 가 아닌 계약 — reviewer 는 누락 시 머지 차단 인지
- CI 게이트 silent 우회 불가; 로컬 훅은 opt-in 개발자에 즉시 피드백

**Costs**

- **Claude Code 기본 worktree 브랜치명(`claude/<adj>-<name>-<hash>`)이 거부됨.** 기여자는 PR 전 rename 필요(`git branch -m feat/issue-<N>-<slug>`). 브랜치당 1회 rename, commit 시점이 아닌 브랜치 생성 시점 비용
- PR 당 workflow run 1회 추가. 빠름(~15s, 코드 checkout 없음)
- bot(Dependabot·Renovate)은 prefix 면제; 그들 PR 은 trusted
- 일부 정당한 작업(작은 오타 수정·doc-only follow-up)도 이제 이슈 선행 필요. uniform 추적성 대가로 friction 수용

**도입된 제약**

- `scripts/check_branch_and_issue.py` 가 regex 단일 출처. 향후 변경(허용 prefix·면제·slug shape)은 그 파일 + 테스트 `tests/test_branch_convention.py` 편집 — CI workflow 나 훅에 regex 중복 절대 X
- `main` 의 branch protection 은 known-good PR 1건 green + deliberate probe red 확인 **후** *"Branch & Issue Convention"* 을 required status check 로 표시

## 검토한 대안

- **`claude/issue-<N>-<slug>` 허용 + auto-name 패턴만 거부.** Reject: 사용자가 conventional-commit 타입 선호로 `claude/` prefix drop 을 명시 선택. 또한 브랜치명을 commit 메시지 컨벤션과 정렬 + 브랜치 리스트가 카테고리 changelog 처럼 읽힘(`feat/`·`fix/`·`docs/` 즉시 가독)
- **multi-issue 작업에 `epic/<slug>` 를 issue-less 예외로 허용.** Reject: epic 자체가 추적 이슈. epic-issue 번호를 브랜치명에 강제(예: `feat/issue-<epic-N>-multi-doc-retrieval`)는 uniformity 의 작은 대가
- **로컬 훅만 강제, CI 비강제.** Reject: 기존 훅은 opt-in(`git config core.hooksPath .githooks`). CI 없으면 `make install-hooks` 안 한 기여자가 rule 을 silent 우회. CI 가 유일한 universal 표면
- **이슈 *body* 검증(예: checklist 요구).** Reject as scope creep. 이 ADR 은 추적성, 이슈 위생 아님. 이슈 템플릿([`.github/ISSUE_TEMPLATE/`](../../.github/ISSUE_TEMPLATE/))이 강제 없이 위생 장려
- **`Closes #N` 만 검사, 브랜치 `<N>` 매칭 안 함.** Reject: `Closes #50` 인데 `feat/issue-49-…` 에 사는 PR 은 거의 확실히 실수 — 브랜치 재사용 또는 sibling PR body 복붙. 매칭이 이를 잡음
