# Worktree 정리 자동화 — 구현 plan (spawn 세션 핸드오프)

이 문서는 별도 cmux 트랙 세션이 **재유도 없이** 구현하도록 만든 핸드오프 plan 이다.
원본 세션(issue #1767 후속)에서 설계를 확정했고, 사용자 결정 4개가 모두 반영돼 있다.
이 worktree 는 origin/main 기반이므로, 먼저 이 plan 을 `docs/plans/worktree-cleanup-automation.md`
로 복사해 PR1 에 함께 커밋하라(설계 기록 보존).

---

## 0. 사용자 결정 (확정 — 재논의 불필요)

1. **범위 = 통합**. ship-pr 의 단계별 게이트 통제(수동)는 유지하되, 머지된 worktree+브랜치
   정리는 자동화한다. ship-arm(완전 자동 ship)으로 전환하는 게 아니다.
2. **self-worktree 정리 = SessionStart 다음-세션-청소** (SessionEnd 아님). 세션 종료 시점이
   "worktree 작업 끝"을 보장하지 않으므로(잠깐 닫았다 다시 열 수 있음), SessionEnd 즉시삭제는
   배제. 대신 다음 세션 시작 때 정리.
3. **자동 수준 = SessionStart 자동 삭제** (경고만 아님). 3가드(self-skip / clean / 머지확정)로
   "남은 할 일"을 보호하므로 자동 실삭제를 default 로 한다.
4. **착수 = spawn-track 새 세션** (이 세션이 그 결과다 — `make spawn-track` dogfood).

---

## 1. 배경 / 발견 (왜 이 범위인가)

- **`make ship-arm`(자동 ship)은 이미 머지 후 정리를 전부 한다.** `scripts/claude-hooks/stop-ship.sh`
  `stage_5_merge()` (line 482-503): `git branch -D` + `git checkout main` 후
  `git worktree remove --force`(자기 worktree 까지, issue #520) + `stage_5_delete_remote_branch`
  (stacked 확인 후 `git push origin --delete`). → **gap 은 자동 경로엔 없다.**
- **gap 은 수동 경로뿐**: (1) `make worktree-cleanup`(=`_pre-push-worktree-hygiene.sh --clean --prune`)
  은 `git worktree remove` 만 하고 **`git branch -D` 안 함**. (2) `ship-pr` SKILL 은 머지 후
  cleanup 단계 자체가 없음.
- **self-worktree 구조 한계**: 현재 cwd 가 점유 중인 worktree 는 그 세션에서 못 지운다.
  `git worktree remove --force` 는 cwd 점유와 무관하게 작동하지만(디렉토리 강제 삭제), 그건
  "마지막 동작"일 때만 안전(이후 명령이 cwd 잃고 깨짐). ship-arm 은 세션 종료 후 외부
  프로세스라 안전하게 자기를 지운다. ship-pr(세션 내 동기)은 불가 → **다음-세션-청소가 유일 경로**.
- **`_pre-push-worktree-hygiene.sh` 는 이미 self-skip + clean + 4신호 머지확정을 다 한다.**
  그래서 SessionStart 가 `make worktree-cleanup` 을 호출하기만 하면 self-worktree 보호가
  공짜로 따라온다. **SessionEnd 마커 메커니즘은 불필요.**

### self-skip 이 "남은 할 일"을 보호하는 원리 (사용자 핵심 우려에 대한 답)

| "남은 할 일" 형태 | 가드 (기존 스크립트) | 결과 |
|---|---|---|
| 미커밋 변경 있음 | `_is_clean_worktree` clean 체크 | 스킵 → 보호 |
| 아직 머지 안 됨 | 4신호 머지확정((a)ancestor (b)`git cherry` patch-equiv (c)`[gone]` (d)opt-in gh) | 스킵 → 보호 |
| 머지+clean, 근데 그 worktree 다시 씀 | self_top self-skip(현재 cwd) | 다시 열면 스킵 → 보호 |
| 머지+clean+진짜 안 씀 | (3가드 통과) | 정리 |

핵심: **남은 할 일이 있으면 사용자는 그 worktree 를 다시 연다 → 그 순간 self-skip 이 보호한다.**

---

## 2. PR1 — `feat(hooks): worktree-cleanup 에 --delete-branches`

ADR **불요**(기존 hygiene 스크립트 확장, `scripts/_governance.py` `LOAD_BEARING_PATHS` 미포함 =
load-bearing 아님, soft-warn 계약 무손상). issue 는 spawn 시 이미 생성됨(`ISSUE=N` 으로 전달받음).

### 2a. `.githooks/_pre-push-worktree-hygiene.sh`

- arg 파서에 `--delete-branches) delete_branches=1 ;;` 추가 + `delete_branches=0` 초기화 + `--help` 갱신.
- clean orphan 제거 루프에서 `git worktree remove` **성공 직후**, 점유 해제된 머지-확정 브랜치를
  삭제하는 블록 삽입:
  - `delete_branches=1` 이고 `dry_run != 1` → `git branch -D "<branch>"` (soft, `|| true`, 성공/실패 로그).
  - `dry_run=1` → `would delete branch '<branch>'` 출력.
- **반드시 `-D`**(force). squash-merge 브랜치는 patch-equiv 라 ancestor 가 아니어서 `git branch -d`
  가 "not fully merged" 로 거부함. 4신호가 머지를 이미 확정했으므로 `-D` 가 정당.
- soft-warn 계약 유지: 실패해도 항상 exit 0, `set -e` 없음. self_top 스킵은 그대로(자기 브랜치는
  애초에 후보에서 빠짐).

### 2b. `Makefile`

- `worktree-cleanup:` → `bash .githooks/_pre-push-worktree-hygiene.sh --clean --prune --delete-branches`
- `worktree-cleanup-dry-run:` → `... --clean --dry-run --delete-branches`
- 보존 변형은 만들지 않는다(요청이 "gap 추가" = 기본 cleanup 이 브랜치까지 정리).

### 2c. `tests/test_hook_pre_push_worktree_hygiene.py`

기존 인프라(real temp git repo + `git worktree`, stub 불필요) 재사용. 추가:
- `test_delete_branches_removes_merged_branch`: `--clean --delete-branches` → worktree 제거 +
  `git show-ref refs/heads/<b>` 비0(삭제됨).
- `test_delete_branches_dry_run_keeps_branch`: `--clean --dry-run --delete-branches` →
  worktree·브랜치 모두 잔존 + stderr "would delete branch".
- `test_delete_branches_off_by_default_after_remove`: `--clean`(플래그 없이) → 브랜치 보존(회귀 가드).
- dirty orphan + `--delete-branches` → 둘 다 보존(dirty 는 애초 스킵) 1건 권장.
- 기존 scenario 14(`test_clean_removes_clean_orphan_without_deleting_branch`)는 **유지**
  (`--clean` 단독 = 브랜치 보존 = 하위호환 계약).

---

## 3. PR2 — `feat(ship): SessionStart 자동 worktree 정리 + ADR` (PR1 머지 후)

ADR **필요**: 자동 파괴적 트리거(SessionStart 자동삭제) + 신규 자동화 표면(SessionStart 훅 최초 도입).

### 3a. `scripts/claude-hooks/sessionstart-worktree-hygiene.sh` (신규)

- 세션 시작 시 이전 세션이 남긴 머지+clean orphan 을 **실제 정리**(사용자 결정 = 자동삭제).
- 다른 훅처럼 `set -u`, soft(항상 exit 0).
- 호출: `make worktree-cleanup` (= `_pre-push-worktree-hygiene.sh --clean --prune --delete-branches`).
  3가드(self-skip/clean/4신호)가 스크립트에 이미 있으므로 별도 안전장치 불필요.
- 성능: orphan 0 이면 즉시 종료(스크립트가 early-exit). SessionStart 지연 상한을 위해
  `BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET` 를 낮춰(예: 5) 호출하는 것을 고려(누적 worktree 多 시
  cherry walk 비용 — OOM 가드 변수는 스크립트에 이미 존재).
- 정리한 게 있으면 stdout 에 1줄 요약("removed N merged worktree(s)").

### 3b. `.claude/settings.json`

- 최상위 `"hooks"` 에 `"SessionStart"` 키 신규 추가(현재 미존재):
  command = `bash scripts/claude-hooks/sessionstart-worktree-hygiene.sh`.
- 이 파일은 자동화 표면(CLAUDE.md) — PR body 에 명시. SessionStart 가 세션 시작을 지연시키지
  않도록 early-exit 보장.

### 3c. `.claude/skills/ship-pr/SKILL.md`

- step 12(merge gate) 직후, mutex release 전에 **step 12b "로컬 cleanup 안내"** 추가:
  - 머지 성공 후 `make worktree-cleanup-dry-run` 으로 지울 목록 출력.
  - **현재 worktree 는 이 세션에서 자동삭제 불가**(cwd 점유) — 다음 세션 SessionStart 가 정리함을 안내.
  - 다른 orphan 즉시 정리 원하면 `make worktree-cleanup` 명시 실행 안내(게이트).
- "What this skill does NOT do" 에 "현재 worktree 자체는 삭제하지 않음(구조적 cwd 점유)" 추가.

### 3d. ADR `docs/adr/NNNN-auto-worktree-branch-cleanup.md` (신규)

- **번호 예약 필수**(CLAUDE.md, ship-pr step 3): `ls docs/adr/` + `gh pr list --search "ADR" --state open`
  양쪽 확인 후 `max+1`. 동시 worktree 충돌 빈발 — 절대 생략 금지.
- Status / Context / Decision / Consequences / Alternatives.
- 핵심 결정: (1) SessionStart 자동삭제 default, 3가드로 안전, (2) self-worktree 는 다음-세션-청소
  (세션 내 즉시삭제 구조 불가), (3) remote delete 는 cleanup 범위 외(ship-pr/ship-arm 담당),
  (4) `--delete-branches` 는 `-D`(squash-merge patch-equiv).
- 링크: issue #520(ship-arm self-clean), `docs/operations/auto-ship.md`, ADR 0007.

### 3e. `tests/`

- `sessionstart-worktree-hygiene.sh` 동작 테스트: 임시 repo + 머지 orphan → 훅 실행 → exit 0 +
  orphan **실제 삭제됨** + **self(현재 cwd) 보호** + **dirty 보호**(3가드 회귀 가드 — 가장 중요).
- `.claude/settings.json` SessionStart 키 존재 + JSON 유효성.
- `ship-pr/SKILL.md` substring("worktree-cleanup", 현재 worktree 한계 문구).

---

## 4. 안전 모델

- **자동 실행(SessionStart) = 실삭제**, 단 3가드(self-skip/clean/머지확정)가 "남은 할 일"의 모든
  형태를 커버. 사용자가 명시 승인한 default.
- **clean-only 불변식**: dirty/untracked 는 항상 스킵 → 미커밋 손실 0.
- **4신호 머지확정 불변식**: 머지 안 된 브랜치는 후보 제외 → `branch -D` 가 미머지 작업 날릴 위험 0.
- **유일 엣지**: 머지+clean 인 worktree 를 안 열고 다른 데서 세션 시작하면 정리됨. 단 머지된
  worktree 재활용은 안티패턴(브랜치 이미 머지 → 새 작업은 새 worktree)이라 실무상 안전. ADR 에 명시.
- 파괴적 op 자동화지만 사용자 결정 + memory `feedback_destructive_op_precheck` 의 정신(3가드 =
  prior-decision 대조 등가)을 충족.

---

## 5. 출하 (ship-pr)

- 두 PR 모두 `/ship-pr` 워크플로 적합(ADR 예약·stacked 감사·게이트). 로컬 게이트는 FlagEmbedding
  설치 환경이면 `make test-fast`(real-model `slow` 제외, CI 커버) + `ruff check .`.
- PR2 가 `ship-pr/SKILL.md` 자체를 수정하므로, PR2 출하는 변경 전 절차로 진행하고 변경은 머지 후 검증.
- 브랜치: PR1 = `feat/issue-<A>-...`(spawn 이 생성), PR2 = `feat/issue-<B>-...`(PR1 머지 후 issue 새로
  생성 — gh issue create 는 글로벌 자율 예외). PR2 worktree 는 `make spawn-track` 또는
  `git worktree add ... origin/main`.

---

## 6. 리스크 / 미해결

- **self 즉시소멸 불가**(구조) → 다음-세션. 사용자 인지·수용함. ship-pr 세션 내에서 이 worktree
  는 안 사라지고, 다음에 다른 worktree 에서 세션 열 때 정리된다.
- SessionStart 세션 시작 지연 — cherry budget 낮춰 상한. 측정 후 조정.
- ADR 번호 동시 충돌 — PR2 작성 전 예약 필수.

---

## 7. 진행 순서 요약

1. 이 plan 을 `docs/plans/worktree-cleanup-automation.md` 로 복사(PR1 에 포함).
2. PR1 구현(2a~2c) → 로컬 게이트 → `/ship-pr`(issue #<A>) → 머지.
3. PR2 issue 생성 → PR2 worktree → 구현(3a~3e, ADR 번호 예약) → 로컬 게이트 → `/ship-pr` → 머지.
4. 머지 후 이 plan 파일(`/Users/hskim/Desktop/projects/bidmate-wt/worktree-cleanup-plan.md`,
   worktree 밖 임시 핸드오프)은 삭제해도 됨.
