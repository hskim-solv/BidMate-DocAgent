# 0096: SessionStart 머지 worktree 자동 정리 (다음-세션-청소)

- Status: accepted
- Date: 2026-06-02
- Deciders: User, Claude Code
- Related: [ADR 0007](./0007-issue-linked-branch-naming.md) (브랜치/이슈 컨벤션 — orphan worktree 누적이 위협하는 "동시 worktree → ADR 번호 충돌" 실패 모드의 대상), [ADR 0066](./0066-codex-pr-adversarial-review.md) (load-bearing local 자동화 표면 선례)
- Issue: #1783

## Context

머지된 worktree 정리에는 두 축이 있다 — **무엇을 지우나**(worktree + 로컬 브랜치 + 원격 브랜치)와
**언제 트리거하나**(수동 / 자동).

- **무엇** 축의 gap 은 PR1(#1781 → #1782)이 닫았다: `make worktree-cleanup`
  (= `_pre-push-worktree-hygiene.sh --clean --prune --delete-branches`)이 이제 머지 orphan
  worktree 를 제거하고 그 로컬 브랜치까지 `git branch -D` 한다.
- **언제** 축은 여전히 수동이다: 정리는 사용자가 `make worktree-cleanup` 을 명시 실행해야 돈다.
  머지된 worktree 가 누적되면 CLAUDE.md 가 반복 인용하는 "동시 worktree → ADR 번호 충돌"
  실패 모드가 재발한다.

자동 ship 경로(`make ship-arm`, `scripts/claude-hooks/stop-ship.sh` `stage_5_merge`)는 머지 후
`git branch -D` + `git worktree remove --force`(자기 worktree 까지, issue #520) + 원격 브랜치
삭제를 **세션 종료 후 외부 프로세스**로 수행하므로 자기 자신을 안전하게 지운다. 그러나 수동
게이트 경로(`ship-pr` skill, 세션 내 동기 실행)는 **현재 cwd 가 점유 중인 worktree 를 그 세션에서
못 지운다** — `git worktree remove --force` 가 디렉토리를 강제 삭제할 수는 있어도 그 이후 명령이
cwd 를 잃고 깨지므로, "마지막 동작"일 때만 안전하다. 따라서 self-worktree 는 **다음 세션 시작
시점**에 정리하는 것이 유일하게 안전한 경로다.

`_pre-push-worktree-hygiene.sh` 는 이미 3가드(① self-skip = 현재 cwd 제외 ② clean-only =
dirty/untracked 스킵 ③ 4신호 머지확정 = ancestor / `git cherry` patch-equiv / `[gone]` upstream /
opt-in gh)를 갖췄다. 그러므로 SessionStart 가 `make worktree-cleanup` 을 호출하기만 하면
self-worktree 보호가 공짜로 따라오고, 별도 SessionEnd 마커 메커니즘은 불필요하다.

## Decision

1. **SessionStart 자동삭제를 default 로 한다 (경고만 아님).** 세션 시작 시 이전 세션이 남긴
   머지+clean orphan worktree 와 그 브랜치를 실제로 정리한다. 3가드가 "남은 할 일"의 모든 형태를
   보호한다: 미커밋 → clean 체크가 스킵, 미머지 → 4신호가 후보 제외, 머지+clean+재사용 → 사용자가
   그 worktree 를 다시 여는 순간 self-skip 이 보호. 신규 훅
   `scripts/claude-hooks/sessionstart-worktree-hygiene.sh` 는 `set -u` + 항상 `exit 0`(soft) +
   orphan 0 이면 early-exit 하며 `make worktree-cleanup` 을 호출한다(플래그 조합 SSoT 는 Makefile).
2. **self-worktree 는 다음-세션-청소 모델을 쓴다 (SessionEnd 즉시삭제 아님).** 세션 종료가 "작업
   끝"을 보장하지 않으므로(잠깐 닫았다 다시 열 수 있음) SessionEnd 즉시삭제는 배제하고, 다음 세션
   SessionStart 가 정리한다.
3. **원격 브랜치 삭제는 cleanup 범위 밖이다.** `git push origin --delete` 는 stacked-dependent
   감사가 선행돼야 하는 별도 op 로, `ship-pr` / `ship-arm` 이 담당한다(CLAUDE.md `## Prohibited`,
   issue #1283). SessionStart 정리는 로컬 worktree + 로컬 브랜치만 건드린다.
4. **`--delete-branches` 는 `git branch -D`(force) 다.** squash-merge tip 은 patch-equivalent 일
   뿐 ancestor 가 아니라 `git branch -d` 가 "not fully merged" 로 거부한다. 4신호가 머지를 이미
   확정했으므로 `-D` 가 정당하다(PR1 결정 승계).

## Drivers

1. **이미 있는 3가드 재사용** — `_pre-push-worktree-hygiene.sh` 의 self-skip/clean/4신호가
   "남은 할 일" 보호의 단일 출처. SessionStart 는 트리거 시점만 제공한다.
2. **self 즉시소멸의 구조적 불가** — 세션 내 동기 경로는 cwd 점유 worktree 를 안전하게 못 지운다.
   다음-세션-청소가 유일 경로.
3. **SSoT** — 플래그 조합(`--clean --prune --delete-branches`)은 `make worktree-cleanup` 한 곳에만
   둔다. 훅은 make 를 호출할 뿐 플래그를 중복하지 않는다(drift 방지).

## Alternatives considered

- **SessionEnd 즉시삭제 + 마커.** 기각: 세션 종료가 작업 완료를 보장하지 않고, self-worktree 의
  cwd 점유 문제를 SessionEnd 도 동일하게 겪는다. 마커 메커니즘은 3가드와 중복.
- **경고만 (자동삭제 안 함).** 기각: 사용자가 자동삭제 default 를 명시 결정했고, 3가드가 미커밋·
  미머지·재사용을 모두 보호하므로 경고-후-수동은 누적 방치로 회귀한다.
- **훅이 `_pre-push-worktree-hygiene.sh` 를 직접 호출(make 우회).** 기각: 플래그 조합이 Makefile 과
  훅 두 곳에 중복돼 drift 위험. make 경유로 SSoT 유지.

## Consequences

- **유일 엣지**: 머지+clean 인 worktree 를 다시 열지 않고 다른 곳에서 세션을 시작하면 정리된다.
  단 머지된 worktree 재활용은 안티패턴(브랜치 이미 머지 → 새 작업은 새 worktree)이라 실무상 안전.
- **SessionStart 지연**: 누적 worktree 가 많으면 `git cherry` patch-id walk 비용이 든다.
  `BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET` 로 상한을 두며(스크립트에 이미 존재하는 OOM 가드),
  필요 시 SessionStart 호출에서 낮춘다. orphan 0 이면 즉시 종료.
- **SessionStart 훅 최초 도입**: `.claude/settings.json` 에 `SessionStart` 키가 신규 추가된다
  (자동화 표면 추가 — 그래서 본 ADR 이 필요).
- 파괴적 op 자동화이지만 사용자 명시 결정 + memory `feedback_destructive_op_precheck` 의 정신
  (3가드 = prior-decision 대조 등가)을 충족한다. soft-warn exit 0 계약으로 세션 시작을 절대
  차단하지 않는다.

## Verification

```bash
python3 -m pytest -q tests/test_hook_sessionstart_worktree_hygiene.py
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0096-auto-worktree-branch-cleanup.md
git diff --check
```

<!-- verifies-key: scripts/claude-hooks/sessionstart-worktree-hygiene.sh:worktree-cleanup -->
<!-- verifies-key: .claude/settings.json:SessionStart -->
<!-- verifies-key: tests/test_hook_sessionstart_worktree_hygiene.py:test_sessionstart -->
